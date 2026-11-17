"""Public exception evidence without upstream messages or feed rows."""
from pathlib import Path
import re
import traceback


class HarnessError(ValueError):
    """Only raise with messages constructed by the rehearsal harness."""


def public_file(filename):
    path = Path(filename)
    try:
        path = path.resolve().relative_to(Path(__file__).resolve().parents[1])
    except ValueError:
        path = Path(path.name)
    return path.as_posix()


def exception_evidence(exc):
    frames = traceback.extract_tb(exc.__traceback__)
    result = {"error_type": type(exc).__name__, "final_frame": "not available"}
    if frames:
        frame = frames[-1]
        result["final_frame"] = f"{public_file(frame.filename)}:{frame.lineno}"
    if isinstance(exc, HarnessError):
        result["error_message"] = str(exc)
    return result


def process_evidence(output):
    classes = re.findall(r"^([\w.]+(?:Error|Exception)|SystemExit|KeyboardInterrupt)(?::|$)", output, re.M)
    frames = re.findall(r'^\s*File "([^"\n]+)", line (\d+)', output, re.M)
    return {"error_type": classes[-1] if classes else "not available",
            "final_frame": public_file(frames[-1][0]) + ":" + frames[-1][1] if frames else "not available"}
