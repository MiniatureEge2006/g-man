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
from pathlib import Path


APP_USER = "gcoder"
EXECUTION_ROOT = Path("/app/executions")
FILE_RETENTION_SECONDS = 30 * 60
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_LANGUAGES = ["bash", "python", "javascript", "typescript", "php", "ruby", "lua", "go", "rust", "c", "cpp", "csharp", "zig"]


def setup_environment():
    EXECUTION_ROOT.mkdir(mode=0o700, exist_ok=True)
    if os.getuid() == 0:
        os.chown(EXECUTION_ROOT, 1000, 1000)

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_environment()
    for dir_name in os.listdir(EXECUTION_ROOT):
        dir_path = EXECUTION_ROOT / dir_name
        if dir_path.is_dir():
            safe_delete(dir_path)
    yield

app = FastAPI(lifespan=lifespan)

def safe_delete(path: Path):
    for _ in range(3):
        try:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                return True
        except Exception:
            time.sleep(0.1)
    return False

async def validate_file(file: UploadFile):
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_FILE_SIZE:
        raise HTTPException(400, detail=f"File {file.filename} exceeds maximum size of 10MB")
    

    if "../" in file.filename or "/" in file.filename:
        raise HTTPException(400, detail="Invalid filename")

async def execute_code(language: str, code: str, files: List[UploadFile]):
    execution_id = str(uuid.uuid4())
    work_dir = EXECUTION_ROOT / execution_id
    work_dir.mkdir(mode=0o700)

    saved_files = []
    for file in files:
        await validate_file(file)
        file_path = work_dir / file.filename
        with file_path.open('wb') as f:
            content = await file.read()
            f.write(content)
        saved_files.append(file.filename)
    
    output = ""
    output_files: List[str] = []
    return_code: int = 0

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
                if f not in saved_files and (work_dir / f).is_file()
            ]

        elif language in ["javascript", "typescript"]:
            if language == "typescript":
                with (work_dir / "tsconfig.json").open('w') as f:
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
            script_path = work_dir / f"script.{ext}"
            with script_path.open('w') as f:
                f.write(wrapper_code)

            proc = await asyncio.create_subprocess_exec(
                'node', str(script_path),
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

            output = ""
            output_path = work_dir / "__output__.txt"
            if output_path.exists():
                output = output_path.read_text()

            output_files = []
            files_json_path = work_dir / "__files__.json"
            if files_json_path.exists():
                output_files = json.loads(files_json_path.read_text())

            error_path = work_dir / "__error__.txt"
            if error_path.exists():
                return {
                    "output": error_path.read_text(),
                    "files": [],
                    "execution_id": execution_id,
                    "error": True
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
                if f not in saved_files and (work_dir / f).is_file()
            ]
        
        elif language == "php":
            env = os.environ.copy()
            proc = await asyncio.create_subprocess_exec(
                'php', '-r', code,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            return_code = proc.returncode
        
        elif language == "ruby":
            env = os.environ.copy()
            proc = await asyncio.create_subprocess_exec(
                'ruby', '-e', code,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            return_code = proc.returncode

        elif language == "lua":
            env = os.environ.copy()
            proc = await asyncio.create_subprocess_exec(
                'lua', '-e', code,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            return_code = proc.returncode

        elif language == "go":
            env = os.environ.copy()
            go_file = work_dir / "main.go"
            with go_file.open('w') as f:
                f.write(code)
            
            proc = await asyncio.create_subprocess_exec(
                'go', 'run', str(go_file),
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            return_code = proc.returncode

        elif language == "rust":
            env = os.environ.copy()
            rust_file = work_dir / "main.rs"
            with rust_file.open('w') as f:
                f.write(code)
            
            compile_proc = await asyncio.create_subprocess_exec(
                'rustc', str(rust_file), '-o', str(work_dir / 'main'),
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            compile_stdout, compile_stderr = await compile_proc.communicate()
            
            if compile_proc.returncode != 0:
                output = compile_stderr.decode() or "Rust compilation failed"
            else:
                run_proc = await asyncio.create_subprocess_exec(
                    str(work_dir / 'main'),
                    cwd=work_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await run_proc.communicate()
                output = stdout.decode() or stderr.decode()
                return_code = run_proc.returncode

        elif language == "c":
            env = os.environ.copy()
            c_file = work_dir / "main.c"
            with c_file.open('w') as f:
                f.write(code)
            
            compile_proc = await asyncio.create_subprocess_exec(
                'gcc', str(c_file), '-o', str(work_dir / 'main'),
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            compile_stdout, compile_stderr = await compile_proc.communicate()
            
            if compile_proc.returncode != 0:
                output = compile_stderr.decode() or "C compilation failed"
            else:
                run_proc = await asyncio.create_subprocess_exec(
                    str(work_dir / 'main'),
                    cwd=work_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await run_proc.communicate()
                output = stdout.decode() or stderr.decode()
                return_code = run_proc.returncode

        elif language == "cpp":
            env = os.environ.copy()
            cpp_file = work_dir / "main.cpp"
            with cpp_file.open('w') as f:
                f.write(code)
            
            compile_proc = await asyncio.create_subprocess_exec(
                'g++', str(cpp_file), '-o', str(work_dir / 'main'),
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            compile_stdout, compile_stderr = await compile_proc.communicate()
            
            if compile_proc.returncode != 0:
                output = compile_stderr.decode() or "C++ compilation failed"
            else:
                run_proc = await asyncio.create_subprocess_exec(
                    str(work_dir / 'main'),
                    cwd=work_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await run_proc.communicate()
                output = stdout.decode() or stderr.decode()
                return_code = run_proc.returncode

        elif language == "csharp":
            env = os.environ.copy()
            csharp_file = os.path.join(work_dir, "Program.cs")
            with open(csharp_file, "w") as f:
                f.write(code)


            compile_proc = await asyncio.create_subprocess_exec(
                "mcs", "Program.cs",
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            compile_stdout, compile_stderr = await compile_proc.communicate()
    
            if compile_proc.returncode != 0:
                output = compile_stderr.decode() or "C# compilation failed"
            else:
                run_proc = await asyncio.create_subprocess_exec(
                    "mono", "Program.exe",
                    cwd=work_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await run_proc.communicate()
                output = stdout.decode() or stderr.decode()
                return_code = run_proc.returncode

        elif language == "zig":
            env = os.environ.copy()
            zig_file = work_dir / "main.zig"
            with zig_file.open('w') as f:
                f.write(code)
            
            proc = await asyncio.create_subprocess_exec(
                'zig', 'run', str(zig_file),
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() or stderr.decode()
            return_code = proc.returncode


        return {
            "output": output,
            "files": output_files,
            "execution_id": execution_id,
            "error": return_code != 0
        }

    except Exception as e:
        safe_delete(work_dir)
        raise HTTPException(500, detail=str(e))

@app.post("/{language}/execute")
async def execute_endpoint(
    language: str,
    code: str = Form(...),
    files: List[UploadFile] = File([])
):
    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(400, detail="Unsupported language")
    return await execute_code(language, code, files)

@app.get("/files/{execution_id}/{filename}")
async def get_file(
    execution_id: str, 
    filename: str, 
    background_tasks: BackgroundTasks
):
    file_path = EXECUTION_ROOT / execution_id / filename
    
    if not file_path.exists():
        raise HTTPException(404, detail="File not found.")

    async def cleanup():
        await asyncio.sleep(10)
        safe_delete(file_path)
        dir_path = file_path.parent
        if dir_path.exists() and not any(dir_path.iterdir()):
            safe_delete(dir_path)

    background_tasks.add_task(cleanup)
    return FileResponse(file_path)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "user": APP_USER,
        "uid": os.getuid(),
        "execution_root": str(EXECUTION_ROOT),
        "is_empty": len(list(EXECUTION_ROOT.iterdir())) == 0
    }