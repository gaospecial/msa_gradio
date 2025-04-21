import gradio as gr
import subprocess
import os
import sqlite3
import uuid
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

# --- Database configuration ---
DB_FILE = "msa_history.db"

# --- Directory Creation ---
os.makedirs("uploads", exist_ok=True)
os.makedirs("results", exist_ok=True)

# --- Database Function ---
def save_to_db(session_id, task_id, tool, input_file, output_file, timestamp):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO history (session_id, task_id, tool, input_file, output_file, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, task_id, tool, input_file, output_file, timestamp))
        conn.commit()
        conn.close()
        logging.info(f"Saved task {task_id} for session {session_id} to DB.")
    except sqlite3.Error as e:
        logging.error(f"Database error saving task {task_id}: {e}")

# --- Core Logic ---
# Modified session_state handling
def run_alignment(fasta_file_obj, tool, current_session_state, progress=gr.Progress(track_tqdm=True)):
    # Add a check for None state, although initializing should prevent it
    if current_session_state is None:
        logging.error("Session state received as None in run_alignment!")
        current_session_state = {} # Initialize if None unexpectedly

    logging.info(f"Received state in run_alignment: {current_session_state}")

    if fasta_file_obj is None:
        return "请上传FASTA文件。", None, "错误：未上传文件"

    # Use dictionary access (.get, []) on the state dictionary
    session_id = current_session_state.get('session_id')

    if session_id is None:
        session_id = str(uuid.uuid4())
        current_session_state['session_id'] = session_id # Store ID in the dictionary
        logging.info(f"New session created and stored in state: {session_id}")
    else:
        logging.info(f"Using existing session from state: {session_id}")

    task_id = uuid.uuid4().hex
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    input_filename = f"input_{task_id}_{timestamp_str}.fasta"
    output_filename = f"result_{task_id}_{timestamp_str}.aln"
    input_path = os.path.join("uploads", input_filename)
    output_path = os.path.join("results", output_filename)

    try:
        # Check if fasta_file_obj has 'name' attribute (should be TemporaryFileWrapper)
        if not hasattr(fasta_file_obj, 'name'):
             raise TypeError("Invalid file object received.")
        with open(fasta_file_obj.name, "rb") as infile, open(input_path, "wb") as outfile:
             outfile.write(infile.read())
        logging.info(f"Input file saved to {input_path}")
    except (AttributeError, TypeError, Exception) as e:
        logging.error(f"Error saving uploaded file: {e}")
        return f"处理上传文件时出错: {e}", None, "错误：文件保存失败"

    progress(0.1, desc="准备运行比对...")
    status_message = f"正在使用 {tool} 运行比对..."

    try:
        command = []
        if tool == "MAFFT":
            command = ["mafft", "--quiet", input_path]
            progress(0.2, desc=f"运行 {tool}...")
            with open(output_path, "w") as f_out:
                result = subprocess.run(command, stdout=f_out, stderr=subprocess.PIPE, text=True, check=True)
                logging.info(f"MAFFT completed for task {task_id}.")
        elif tool == "MUSCLE":
            # Check Muscle version? V3 uses -in/-out, V5 uses different flags like --align/--output
            command = ["muscle", "-in", input_path, "-out", output_path]
            logging.warning("Assuming MUSCLE v3 syntax (-in/-out). Adjust if using MUSCLE v5.")
            progress(0.2, desc=f"运行 {tool}...")
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            logging.info(f"MUSCLE completed for task {task_id}. Stdout: {result.stdout}, Stderr: {result.stderr}")
        else:
             return "无效的比对工具选择。", None, "错误：无效工具"

    except FileNotFoundError:
        logging.error(f"Error: Command '{command[0]}' not found. Is {tool} installed and in PATH?")
        return f"错误: 命令 '{command[0]}' 未找到。请确保 {tool} 已安装并已添加到系统 PATH。", None, f"错误：{tool} 未找到"
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running {tool} for task {task_id}. Return code: {e.returncode}")
        logging.error(f"Stderr: {e.stderr}")
        # Try to provide more specific error if possible
        error_detail = e.stderr or e.stdout or f"Return code: {e.returncode}"
        return f"{tool} 运行时出错。\n错误信息:\n{error_detail}", None, f"错误：{tool} 运行失败"
    except Exception as e:
        logging.error(f"An unexpected error occurred during alignment: {e}")
        return f"比对过程中发生意外错误: {e}", None, "错误：比对异常"

    progress(0.9, desc="比对完成，读取结果...")
    status_message = f"比对完成 ({tool})。"

    try:
        with open(output_path, "r") as f:
            result_text = f.read()
        logging.info(f"Result file {output_path} read successfully.")
    except Exception as e:
        logging.error(f"Error reading result file {output_path}: {e}")
        return "比对成功，但读取结果文件时出错。", None, "错误：结果读取失败"

    save_to_db(session_id, task_id, tool, input_path, output_path, datetime.now().isoformat())

    # IMPORTANT: Return the updated state dictionary so Gradio persists it
    # However, gr.State() is designed to update implicitly when mutated.
    # Test without returning state first. If state doesn't persist, add current_session_state
    # to the outputs list and return it here.
    return result_text, gr.update(value=output_path), status_message

# --- History Function ---
# Modified session_state handling
def show_history(current_session_state):
    # Add a check for None state
    if current_session_state is None:
        logging.error("Session state received as None in show_history!")
        current_session_state = {}

    logging.info(f"Received state in show_history: {current_session_state}")

    # Use dictionary access (.get)
    session_id = current_session_state.get('session_id')

    if not session_id:
        return "当前会话没有历史记录。"

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, tool,
                   REPLACE(input_file, 'uploads/', '') as input,
                   REPLACE(output_file, 'results/', '') as output
            FROM history
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 20
        """, (session_id,))
        rows = c.fetchall()
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Database error fetching history for session {session_id}: {e}")
        return f"无法加载历史记录: {e}"

    if not rows:
        return f"当前会话 (ID: ...{session_id[-6:]}) 没有历史记录。" # Show partial ID for confirmation

    header = "时间\t工具\t输入文件\t输出文件\n" + "-"*50 + "\n"
    table = header + "\n".join(["\t".join(map(str, row)) for row in rows])
    return table


# --- Gradio Interface ---
with gr.Blocks() as demo:
    gr.Markdown("# 🧬 DNA 多序列比对工具 (MAFFT / MUSCLE)")

    # Initialize gr.State with an empty dictionary
    session_state = gr.State(value={})

    with gr.Tab("比对任务"):
        with gr.Row():
            with gr.Column(scale=1):
                file_input = gr.File(label="上传FASTA文件 (.fasta, .fa)")
                tool_select = gr.Radio(["MAFFT", "MUSCLE"], label="选择比对工具", value="MAFFT")
                run_button = gr.Button("开始比对", variant="primary")
            with gr.Column(scale=2):
                status_output = gr.Textbox(label="状态", interactive=False)
                result_box = gr.Textbox(label="比对结果 (Clustal 格式)", lines=15, interactive=False)
                file_download = gr.File(label="下载比对结果 (.aln)", interactive=False)

    with gr.Tab("历史记录"):
        history_button = gr.Button("刷新记录")
        history_output = gr.Textbox(label="最近 20 条历史记录", lines=15, interactive=False)

    # --- Event Handlers ---
    # Pass the session_state object as input
    run_button.click(
        fn=run_alignment,
        inputs=[file_input, tool_select, session_state], # Pass state object
        # Do NOT list session_state in outputs unless you explicitly return it AND need to overwrite
        outputs=[result_box, file_download, status_output]
    )

    history_button.click(
        fn=show_history,
        inputs=[session_state], # Pass state object
        outputs=history_output
    )

# --- Launch ---
demo.launch(server_name="0.0.0.0", server_port=7860)