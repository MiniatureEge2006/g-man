import asyncio
import json
import os
import shutil
import signal
import tempfile
import time
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

APP_USER = "gcoder"
EXECUTION_BASE = Path("/home/gcoder")
STAGING_BASE = EXECUTION_BASE / "staging"
ALLOWED_LANGUAGES = [
    "bash",
    "fish",
    "nu",
    "python",
    "javascript",
    "typescript",
    "php",
    "ruby",
    "lua",
    "go",
    "rust",
    "c",
    "cpp",
    "csharp",
    "zig",
    "java",
    "kotlin",
    "nim",
]


_active_work_dirs: set[Path] = set()
_active_work_dirs_lock = asyncio.Lock()
_stage_refcounts: dict[str, int] = defaultdict(int)
_stage_refcounts_lock = asyncio.Lock()


def ensure_dirs():
    EXECUTION_BASE.mkdir(mode=0o700, exist_ok=True)
    STAGING_BASE.mkdir(mode=0o700, exist_ok=True)

    if os.getuid() == 0:
        os.chown(EXECUTION_BASE, 1000, 1000)
        os.chown(STAGING_BASE, 1000, 1000)


async def cleanup_execution_base():
    if not EXECUTION_BASE.exists():
        return
    async with _active_work_dirs_lock:
        active = set(_active_work_dirs)
    for entry in EXECUTION_BASE.iterdir():
        if entry == STAGING_BASE:
            continue
        if entry in active:
            continue
        safe_delete(entry)


async def periodic_cleanup(interval: int = 300):
    while True:
        await asyncio.sleep(interval)
        cleanup_execution_base()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    cleanup_execution_base()
    asyncio.create_task(periodic_cleanup())
    yield


app = FastAPI(lifespan=lifespan)


def safe_delete(path: Path):
    if path in [STAGING_BASE, EXECUTION_BASE]:
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
    safe_name = Path(file.filename).name
    if not safe_name or safe_name != file.filename:
        raise HTTPException(400, detail="Invalid filename")
    file.filename = safe_name


async def execute_code(language: str, code: str, files: List[UploadFile]):
    ensure_dirs()
    work_dir = Path(tempfile.mkdtemp(dir=EXECUTION_BASE, prefix="job__"))
    stage_dir = STAGING_BASE / work_dir.name
    work_dir.chmod(0o700)
    input_dir = work_dir / "input"
    input_dir.mkdir(mode=0o700)
    output_dir = work_dir / "output"
    output_dir.mkdir(mode=0o700)

    saved_files = []
    for file in files:
        await validate_file(file)
        file_path = input_dir / file.filename
        with file_path.open("wb") as f:
            content = await file.read()
            f.write(content)
        saved_files.append(file.filename)

    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(work_dir),
    }
    for i, filename in enumerate(saved_files, start=1):
        env[f"FILE_{i}"] = str(input_dir / filename)

    async def run_with_timeout(cmd, cwd=None, env=env, input_data=None):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=input_data), timeout=60
            )
            return stdout.decode("utf-8", errors="replace") + stderr.decode(
                "utf-8", errors="replace"
            ), proc.returncode
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            return "Code execution took longer than 60 seconds", 1

    async with _active_work_dirs_lock:
        _active_work_dirs.add(work_dir)

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
        elif language == "fish":
            fish_file = work_dir / "script.fish"
            with fish_file.open("w") as f:
                f.write(code)
            fish_file.chmod(0o700)
            output, return_code = await run_with_timeout(
                ["fish", str(fish_file)], cwd=work_dir
            )
        elif language == "nu":
            nu_file = work_dir / "script.nu"
            with nu_file.open("w") as f:
                f.write(code)
            nu_file.chmod(0o700)
            output, return_code = await run_with_timeout(
                ["nu", str(nu_file)], cwd=work_dir
            )
        elif language in ["javascript", "typescript"]:
            if language == "typescript":
                script_path = work_dir / "script.ts"
                with script_path.open("w") as f:
                    f.write(code)
                tsconfig = {
                    "compilerOptions": {
                        "target": "ES2020",
                        "module": "CommonJS",
                        "strict": True,
                        "esModuleInterop": True,
                        "skipLibCheck": True,
                        "types": ["node"],
                    },
                    "ts-node": {"transpileOnly": True, "files": True},
                }
                with (work_dir / "tsconfig.json").open("w") as f:
                    json.dump(tsconfig, f)
                cmd = ["ts-node", "--files", "--transpile-only", str(script_path)]
                output, return_code = await run_with_timeout(cmd, cwd=work_dir)
            else:
                js_file = work_dir / "script.js"
                with js_file.open("w") as f:
                    f.write(code)
                output, return_code = await run_with_timeout(
                    ["node", str(js_file)], cwd=work_dir
                )
        elif language == "python":
            py_file = work_dir / "script.py"
            with py_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(
                ["python", str(py_file)], cwd=work_dir
            )
        elif language == "php":
            php_file = work_dir / "script.php"
            with php_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(
                ["php", str(php_file)], cwd=work_dir
            )
        elif language == "ruby":
            rb_file = work_dir / "script.rb"
            with rb_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(
                ["ruby", str(rb_file)], cwd=work_dir
            )
        elif language == "lua":
            lua_file = work_dir / "script.lua"
            with lua_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(
                ["lua", str(lua_file)], cwd=work_dir
            )
        elif language == "go":
            go_file = work_dir / "script.go"
            with go_file.open("w") as f:
                f.write(code)
            output, return_code = await run_with_timeout(
                ["go", "run", str(go_file)], cwd=work_dir
            )
        elif language == "rust":
            rust_file = work_dir / "script.rs"
            with rust_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ["rustc", str(rust_file), "-o", str(work_dir / "script")], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    [str(work_dir / "script")], cwd=work_dir
                )
        elif language == "c":
            c_file = work_dir / "script.c"
            with c_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ["gcc", str(c_file), "-o", str(work_dir / "script")], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    [str(work_dir / "script")], cwd=work_dir
                )
        elif language == "cpp":
            cpp_file = work_dir / "script.cpp"
            with cpp_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ["g++", str(cpp_file), "-o", str(work_dir / "script")], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    [str(work_dir / "script")], cwd=work_dir
                )
        elif language == "csharp":
            cs_file = work_dir / "script.cs"
            with cs_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ["mcs", str(cs_file)], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    ["mono", str(work_dir / "script.exe")], cwd=work_dir
                )
        elif language == "zig":
            zig_file = work_dir / "script.zig"
            with zig_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ["zig", "build-exe", str(zig_file)], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    [str(work_dir / "script")], cwd=work_dir
                )
        elif language == "java":
            java_file = work_dir / "script.java"
            with java_file.open("w") as f:
                f.write(code)

            compile_out, compile_code = await run_with_timeout(
                ["javac", str(java_file)], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    ["java", "-cp", str(work_dir), "script.java"], cwd=work_dir
                )
        elif language == "kotlin":
            kt_file = work_dir / "script.kt"
            with kt_file.open("w") as f:
                f.write(code)

            compile_jar = work_dir / "script.jar"
            compile_out, compile_code = await run_with_timeout(
                ["kotlinc", str(kt_file), "-include-runtime", "-d", str(compile_jar)],
                cwd=work_dir,
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    ["java", "-jar", str(compile_jar)], cwd=work_dir
                )
        elif language == "nim":
            nim_file = work_dir / "script.nim"
            with nim_file.open("w") as f:
                f.write(code)
            compile_out, compile_code = await run_with_timeout(
                ["nim", "c", str(nim_file)], cwd=work_dir
            )
            if compile_code != 0:
                output = compile_out
                return_code = compile_code
            else:
                output, return_code = await run_with_timeout(
                    [str(work_dir / "script")], cwd=work_dir
                )

        ensure_dirs()
        produced = [f for f in output_dir.iterdir() if f.is_file()]
        final_files = []
        if produced:
            stage_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            for f in produced:
                dest = stage_dir / f.name
                shutil.copy2(f, dest)
                final_files.append(f.name)

        return {
            "output": output.strip(),
            "job_id": work_dir.name,
            "files": final_files,
            "error": return_code != 0,
        }

    except Exception as e:
        safe_delete(work_dir)
        print(f"Code execution Error: {traceback.format_exc()}")
        raise HTTPException(500, detail=f"Code execution failed: {str(e)}")
    finally:
        async with _active_work_dirs_lock:
            _active_work_dirs.discard(work_dir)
        safe_delete(work_dir)
        if stage_dir.exists() and not any(stage_dir.iterdir()):
            safe_delete(stage_dir)
        async with _active_work_dirs_lock:
            active = set(_active_work_dirs)
        for entry in EXECUTION_BASE.iterdir():
            if entry == STAGING_BASE:
                continue
            if entry in active:
                continue
            safe_delete(entry)


@app.post("/{language}/execute")
async def execute_endpoint(
    language: str, code: str = Form(...), files: List[UploadFile] = File([])
):
    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(400, detail="Unsupported language")
    return await execute_code(language, code, files)


@app.get("/files/{job_id}/{filename}")
async def get_file(job_id: str, filename: str, background_tasks: BackgroundTasks):
    ensure_dirs()
    stage_dir = STAGING_BASE / job_id
    file_path = stage_dir / filename
    if not file_path.exists():
        raise HTTPException(404, detail="File not found.")

    async def cleanup():
        await asyncio.sleep(10)
        async with _stage_refcounts_lock:
            _stage_refcounts[job_id] -= 1
            if _stage_refcounts[job_id] <= 0:
                del _stage_refcounts[job_id]
                safe_delete(stage_dir)

    background_tasks.add_task(cleanup)
    return FileResponse(file_path)


@app.get("/health")
async def health_check():
    ensure_dirs()
    return {
        "status": "healthy",
        "user": APP_USER,
        "uid": os.getuid(),
        "execution_base": str(EXECUTION_BASE),
        "staging_dir_exists": STAGING_BASE.exists(),
    }
