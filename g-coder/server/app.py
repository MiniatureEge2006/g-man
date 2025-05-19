from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
import shutil
import asyncio
import time
import json
from typing import List
from pathlib import Path
import traceback

APP_USER = "gcoder"
EXECUTION_ROOT = Path("/app/executions")
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
    file.file.seek(0)
    if "../" in file.filename or "/" in file.filename:
        raise HTTPException(400, detail="Invalid filename")

async def execute_code(language: str, code: str, files: List[UploadFile]):
    work_dir = EXECUTION_ROOT / "work"
    if work_dir.exists():
        safe_delete(work_dir)
    work_dir.mkdir(mode=0o700)

    saved_files = []
    for file in files:
        await validate_file(file)
        file_path = work_dir / file.filename
        with file_path.open('wb') as f:
            content = await file.read()
            f.write(content)
        saved_files.append(file.filename)

    async def run_with_timeout(cmd, cwd=None, env=None, input_data=None):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=input_data), timeout=60)
            return stdout.decode('utf-8', errors='replace') + stderr.decode('utf-8', errors='replace'), proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return "Code execution took longer than 60 seconds", 1

    try:
        output = ""
        return_code = 1
        if language == "bash":
            output, return_code = await run_with_timeout(['bash', '-c', f"cd '{work_dir}' && {code}"])
        elif language in ["javascript", "typescript"]:
            if language == "typescript":
                script_path = work_dir / "script.ts"
                with script_path.open('w') as f:
                    f.write(code)
                tsconfig = {
                    "compilerOptions": {
                        "target": "ES2020",
                        "module": "CommonJS",
                        "strict": True,
                        "esModuleInterop": True,
                        "skipLibCheck": True,
                        "types": ["node"]
                    },
                    "ts-node": {
                        "transpileOnly": True,
                        "files": True
                    }
                }
                with (work_dir / 'tsconfig.json').open('w') as f:
                    json.dump(tsconfig, f)
                cmd = ['ts-node', '--files', '--transpile-only', str(script_path)]
                output, return_code = await run_with_timeout(cmd, cwd=work_dir)
            else:
                escaped_code = json.dumps(code)
                wrapper = f"""
                (async () => {{
                    try {{
                        eval({escaped_code});
                        await new Promise(r => setTimeout(r, 50));
                    }} catch (e) {{
                        console.error(e.stack || e);
                        process.exit(1);
                    }}
                }})();
                """
                output, return_code = await run_with_timeout(['node', '-e', wrapper], cwd=work_dir)
        elif language == "python":
            output, return_code = await run_with_timeout(['python', '-c', code], cwd=work_dir)
        elif language == "php":
            output, return_code = await run_with_timeout(['php', '-r', code], cwd=work_dir)
        elif language == "ruby":
            output, return_code = await run_with_timeout(['ruby', '-e', code], cwd=work_dir)
        elif language == "lua":
            output, return_code = await run_with_timeout(['lua', '-e', code], cwd=work_dir)
        elif language == "go":
            go_file = work_dir / "main.go"
            with go_file.open('w') as f:
                f.write(code)
            output, return_code = await run_with_timeout(['go', 'run', str(go_file)], cwd=work_dir)
        elif language == "rust":
            rust_file = work_dir / "main.rs"
            with rust_file.open('w') as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ['rustc', str(rust_file), '-o', str(work_dir / 'main')], cwd=work_dir)
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout([str(work_dir / 'main')], cwd=work_dir)
        elif language == "c":
            c_file = work_dir / "main.c"
            with c_file.open('w') as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ['gcc', str(c_file), '-o', str(work_dir / 'main')], cwd=work_dir)
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout([str(work_dir / 'main')], cwd=work_dir)
        elif language == "cpp":
            cpp_file = work_dir / "main.cpp"
            with cpp_file.open('w') as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ['g++', str(cpp_file), '-o', str(work_dir / 'main')], cwd=work_dir)
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout([str(work_dir / 'main')], cwd=work_dir)
        elif language == "csharp":
            cs_file = work_dir / "Program.cs"
            with cs_file.open('w') as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(['mcs', str(cs_file)], cwd=work_dir)
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(['mono', str(work_dir / 'Program.exe')], cwd=work_dir)
        elif language == "zig":
            zig_file = work_dir / "main.zig"
            with zig_file.open('w') as f:
                f.write(code)
            output, return_code = await run_with_timeout(['zig', 'run', str(zig_file)], cwd=work_dir)

        TEMP_FILES = {
            "zig": ["main.zig"],
            "go": ["main.go"],
            "rust": ["main.rs", "main"],
            "c": ["main.c", "main"],
            "cpp": ["main.cpp", "main"],
            "csharp": ["Program.cs", "Program.exe"],
            "typescript": ["tsconfig.json", "script.ts"],
            "javascript": [],
            "python": ["__pycache__"],
            "php": [],
            "ruby": [],
            "lua": [],
            "bash": []
        }

        excluded_files = TEMP_FILES.get(language, [])
        output_files = [
            f for f in os.listdir(work_dir)
            if f not in saved_files and (work_dir / f).is_file()
        ]
        final_files = [f for f in output_files if f not in excluded_files]

        return {
            "output": output.strip(),
            "files": final_files,
            "execution_id": "work",
            "error": return_code != 0
        }

    except Exception as e:
        safe_delete(work_dir)
        print(f"Code execution Error: {traceback.format_exc()}")
        raise HTTPException(500, detail=f"Code execution failed: {str(e)}")


@app.post("/{language}/execute")
async def execute_endpoint(
    language: str,
    code: str = Form(...),
    files: List[UploadFile] = File([])
):
    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(400, detail="Unsupported language")
    return await execute_code(language, code, files)


@app.get("/files/{filename}")
async def get_file(
    filename: str,
    background_tasks: BackgroundTasks
):
    file_path = EXECUTION_ROOT / "work" / filename
    if not file_path.exists():
        raise HTTPException(404, detail="File not found.")

    async def cleanup():
        await asyncio.sleep(10)
        safe_delete(file_path)

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