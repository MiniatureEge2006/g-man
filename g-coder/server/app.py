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
EXECUTION_DIR = Path("/home/gcoder/executions")
INPUT_DIR = EXECUTION_DIR / "input"
OUTPUT_DIR = EXECUTION_DIR / "output"
ALLOWED_LANGUAGES = ["bash", "python", "javascript", "typescript", "php", "ruby", "lua", "go", "rust", "c", "cpp", "csharp", "zig", "java", "kotlin", "nim"]

def ensure_dirs():
    EXECUTION_DIR.mkdir(mode=0o700, exist_ok=True)
    INPUT_DIR.mkdir(mode=0o700, exist_ok=True)
    OUTPUT_DIR.mkdir(mode=0o700, exist_ok=True)
    
    if os.getuid() == 0:
        os.chown(EXECUTION_DIR, 1000, 1000)
        os.chown(INPUT_DIR, 1000, 1000)
        os.chown(OUTPUT_DIR, 1000, 1000)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    yield

app = FastAPI(lifespan=lifespan)

def safe_delete(path: Path):
    if path in [INPUT_DIR, OUTPUT_DIR]:
        return False
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
    ensure_dirs()
    work_dir = EXECUTION_DIR
    for item in work_dir.iterdir():
        if item.name not in ['input', 'output'] and item.is_dir():
            safe_delete(item)
        elif item.name not in ['input', 'output'] and item.is_file():
            item.unlink(missing_ok=True)

    saved_files = []
    for file in files:
        await validate_file(file)
        file_path = INPUT_DIR / file.filename
        with file_path.open('wb') as f:
            content = await file.read()
            f.write(content)
        saved_files.append(file.filename)
    
    env = os.environ.copy()
    for i, filename in enumerate(saved_files, start=1):
        env[f"FILE_{i}"] = str(INPUT_DIR / filename)

    async def run_with_timeout(cmd, cwd=None, env=env, input_data=None):
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
            sh_file = work_dir / "script.sh"
            with sh_file.open("w") as f:
                f.write("#!/bin/bash\n")
                f.write(code)
            sh_file.chmod(0o700)
            output, return_code = await run_with_timeout([str(sh_file)], cwd=work_dir)
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
                js_file = work_dir / "script.js"
                with js_file.open("w") as f:
                    f.write(code)
                output, return_code = await run_with_timeout(['node', str(js_file)], cwd=work_dir)
        elif language == "python":
            py_file = work_dir / "script.py"
            with py_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(['python', str(py_file)], cwd=work_dir)
        elif language == "php":
            php_file = work_dir / "script.php"
            with php_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(['php', str(php_file)], cwd=work_dir)
        elif language == "ruby":
            rb_file = work_dir / "script.rb"
            with rb_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(['ruby', str(rb_file)], cwd=work_dir)
        elif language == "lua":
            lua_file = work_dir / "script.lua"
            with lua_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(['lua', str(lua_file)], cwd=work_dir)
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
        elif language == "java":
            java_class_name = "Main"
            java_file = work_dir / f"{java_class_name}.java"
            with java_file.open("w") as f:
                f.write(code)
            
            compile_out, compile_code = await run_with_timeout(['javac', str(java_file)], cwd=work_dir)
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(['java', '-cp', str(work_dir), java_class_name], cwd=work_dir)
        elif language == "kotlin":
            kt_file = work_dir / "Main.kt"
            with kt_file.open("w") as f:
                f.write(code)
            
            compile_jar = work_dir / "main.jar"
            compile_out, compile_code = await run_with_timeout(['kotlinc', str(kt_file), '-include-runtime', '-d', str(compile_jar)], cwd=work_dir)
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(['java', '-jar', str(compile_jar)], cwd=work_dir)
        elif language == "nim":
            nim_file = work_dir  / "script.nim"
            with nim_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ['nim', 'c', str(nim_file)], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout([str(work_dir / 'script')], cwd=work_dir)

        ensure_dirs()
        final_files = [f for f in os.listdir(OUTPUT_DIR) if f not in saved_files and (OUTPUT_DIR / f).is_file()]

        return {
            "output": output.strip(),
            "files": final_files,
            "error": return_code != 0
        }

    except Exception as e:
        safe_delete(work_dir)
        print(f"Code execution Error: {traceback.format_exc()}")
        raise HTTPException(500, detail=f"Code execution failed: {str(e)}")
    finally:
        for filename in saved_files:
            file_path = INPUT_DIR / filename
            safe_delete(file_path)
        ensure_dirs()


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
    ensure_dirs()
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, detail="File not found.")

    async def cleanup():
        await asyncio.sleep(10)
        safe_delete(file_path)

    background_tasks.add_task(cleanup)
    return FileResponse(file_path)


@app.get("/health")
async def health_check():
    ensure_dirs()
    return {
        "status": "healthy",
        "user": APP_USER,
        "uid": os.getuid(),
        "execution_dir": str(EXECUTION_DIR),
        "input_dir_exists": INPUT_DIR.exists(),
        "output_dir_exists": OUTPUT_DIR.exists(),
        "is_empty": len(list(EXECUTION_DIR.iterdir())) == 0
    }