from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
import uuid
import shutil
import asyncio
import time
import json
from typing import List

EXECUTION_ROOT = "/tmp/code_executions"
os.makedirs(EXECUTION_ROOT, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    for dir_name in os.listdir(EXECUTION_ROOT):
        dir_path = os.path.join(EXECUTION_ROOT, dir_name)
        if os.path.isdir(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
    yield

app = FastAPI(lifespan=lifespan)

def safe_delete(path: str):
    for _ in range(3):
        try:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                return True
        except Exception:
            time.sleep(0.1)
    return False

async def execute_code(language: str, code: str, files: List[UploadFile]):
    execution_id = str(uuid.uuid4())
    work_dir = os.path.join(EXECUTION_ROOT, execution_id)
    os.makedirs(work_dir, exist_ok=True)


    saved_files = []
    for file in files:
        file_path = os.path.join(work_dir, file.filename)
        with open(file_path, 'wb') as f:
            content = await file.read()
            f.write(content)
        saved_files.append(file.filename)

    try:
        if language == "bash":
            proc = await asyncio.create_subprocess_exec(
                'bash', '-c', f"cd '{work_dir}' && {code}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            
            output_files = [
                f for f in os.listdir(work_dir)
                if f not in saved_files and os.path.isfile(os.path.join(work_dir, f))
            ]

        elif language in ["javascript", "typescript"]:
            if language == "typescript":
                with open(os.path.join(work_dir, "tsconfig.json"), 'w') as f:
                    f.write(json.dumps({
                        "compilerOptions": {
                            "module": "commonjs",
                            "esModuleInterop": True
                        }
                    }))


            wrapper_code = f"""
            const fs = require('fs');
            const {{ spawnSync }} = require('child_process');
            let output = '';
            
            try {{
                // Execute user code with proper module handling
                const cmd = '{'node' if language == 'javascript' else 'ts-node'}';
                const args = {{
                    javascript: ['-e', `{code.replace('`', '\\`')}`],
                    typescript: ['--esm', '-e', `{code.replace('`', '\\`')}`]
                }};
                
                const result = spawnSync(cmd, args['{language}'], {{
                    cwd: process.cwd(),
                    encoding: 'utf-8',
                    stdio: ['inherit', 'pipe', 'pipe']
                }});
                
                output = result.stdout || result.stderr;
                
                // Get only user-created files
                const allFiles = fs.readdirSync('.');
                const tempFiles = ['script.{'js' if language == 'javascript' else 'ts'}', 
                                'tsconfig.json',
                                '__output__.txt',
                                '__files__.json',
                                '__error__.txt'];
                const newFiles = allFiles.filter(f => 
                    ![...{json.dumps(saved_files)}, ...tempFiles].includes(f));
                
                fs.writeFileSync('__output__.txt', output);
                fs.writeFileSync('__files__.json', JSON.stringify(newFiles));
            }} catch (e) {{
                fs.writeFileSync('__error__.txt', e.stack);
            }}
            """
            
            ext = "js" if language == "javascript" else "ts"
            script_path = os.path.join(work_dir, f"script.{ext}")
            with open(script_path, 'w') as f:
                f.write(wrapper_code)

            proc = await asyncio.create_subprocess_exec(
                'node', script_path,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()


            output = ""
            if os.path.exists(os.path.join(work_dir, "__output__.txt")):
                with open(os.path.join(work_dir, "__output__.txt"), 'r') as f:
                    output = f.read()

            output_files = []
            if os.path.exists(os.path.join(work_dir, "__files__.json")):
                with open(os.path.join(work_dir, "__files__.json"), 'r') as f:
                    output_files = json.load(f)

            if os.path.exists(os.path.join(work_dir, "__error__.txt")):
                with open(os.path.join(work_dir, "__error__.txt"), 'r') as f:
                    return {
                        "output": f.read(),
                        "files": [],
                        "execution_id": execution_id,
                        "error": proc.returncode != 0
                    }

        elif language == "python":
            proc = await asyncio.create_subprocess_exec(
                'python', '-c', code,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            
            output_files = [
                f for f in os.listdir(work_dir)
                if f not in saved_files and os.path.isfile(os.path.join(work_dir, f))
            ]

        return {
            "output": output,
            "files": output_files,
            "execution_id": execution_id,
            "error": proc.returncode != 0 if language != "typescript" else False
        }

    finally:
        pass

@app.post("/{language}/execute")
async def execute_endpoint(
    language: str,
    code: str = Form(...),
    files: List[UploadFile] = File([])
):
    if language not in ["bash", "python", "javascript", "typescript"]:
        raise HTTPException(400, detail="Unsupported language")
    return await execute_code(language, code, files)

@app.get("/files/{execution_id}/{filename}")
async def get_file(
    execution_id: str, 
    filename: str, 
    background_tasks: BackgroundTasks
):
    file_path = os.path.join(EXECUTION_ROOT, execution_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(404, detail="File not found.")

    async def cleanup():
        await asyncio.sleep(10)
        safe_delete(file_path)
        dir_path = os.path.dirname(file_path)
        if os.path.exists(dir_path) and not os.listdir(dir_path):
            safe_delete(dir_path)

    background_tasks.add_task(cleanup)
    return FileResponse(file_path)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "execution_root": EXECUTION_ROOT,
        "is_empty": len(os.listdir(EXECUTION_ROOT)) == 0
    }