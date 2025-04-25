from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
import uuid
import shutil
import asyncio
import aiofiles
from typing import List


EXECUTION_ROOT = "/tmp/code_executions"
os.makedirs(EXECUTION_ROOT, exist_ok=True)
os.chmod(EXECUTION_ROOT, 0o777)

async def async_cleanup(path: str, max_retries: int = 3, delay: float = 0.5):
    for attempt in range(max_retries):
        try:
            temp_dir = f"{path}_delete_{uuid.uuid4()}"
            os.rename(path, temp_dir)
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Background delete failed, retrying... ({str(e)})")
                await asyncio.sleep(delay)
                continue
            os.makedirs(path, exist_ok=True)
            return True
        except OSError as e:
            if attempt == max_retries - 1:
                print(f"Falling back to direct delete for {path}")
                try:
                    # Last resort: delete contents without rename
                    for root, dirs, files in os.walk(path):
                        for f in files:
                            os.unlink(os.path.join(root, f))
                        for d in dirs:
                            shutil.rmtree(os.path.join(root, d))
                    return True
                except Exception as fallback_error:
                    print(f"Critical cleanup failure: {str(fallback_error)}")
                    return False
            await asyncio.sleep(delay * (attempt + 1))
    return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    await async_cleanup(EXECUTION_ROOT)
    yield


app = FastAPI(lifespan=lifespan)

async def execute_code(language: str, code: str, files: List[UploadFile]):
    execution_id = str(uuid.uuid4())
    work_dir = os.path.join(EXECUTION_ROOT, execution_id)
    os.makedirs(work_dir, exist_ok=True)

    try:
        saved_files = []
        for file in files:
            file_path = os.path.join(work_dir, file.filename)
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(await file.read())
            saved_files.append(file.filename)


        if language == "bash":
            proc = await asyncio.create_subprocess_exec(
                'bash', '-c', f"cd {work_dir} && {code} && sync",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        elif language == "python":
            proc = await asyncio.create_subprocess_exec(
                'python', '-c', code,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

        stdout, stderr = await proc.communicate()
        

        output_files = [
            f for f in os.listdir(work_dir)
            if f not in saved_files and os.path.isfile(os.path.join(work_dir, f))
        ]


        response = {
            "output": stdout.decode() or stderr.decode(),
            "files": output_files,
            "execution_id": execution_id,
            "error": proc.returncode != 0
        }

        return response
    finally:
        await async_cleanup(work_dir)

@app.post("/python/execute")
async def execute_python(
    code: str = Form(...),
    files: List[UploadFile] = File([])
):
    return await execute_code("python", code, files)

@app.post("/bash/execute")
async def execute_bash(
    code: str = Form(...),
    files: List[UploadFile] = File([])
):
    return await execute_code("bash", code, files)

@app.get("/files/{execution_id}/{filename}")
async def get_file(execution_id: str, filename: str):
    file_path = os.path.join(EXECUTION_ROOT, execution_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(404, detail="File already cleaned up")
    
    try:
        response = FileResponse(file_path)
        
        return response
    except Exception as e:
        await async_cleanup(os.path.dirname(file_path))
        raise HTTPException(500, detail=str(e))

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "execution_root": EXECUTION_ROOT,
        "is_empty": len(os.listdir(EXECUTION_ROOT)) == 0
    }