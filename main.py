from io import TextIOWrapper
import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dotenv import dotenv_values

# ================= GLOBAL CONFIGURATION =================
ENV_V: dict[str, str] = {
    k: v if v else "" for k, v in dotenv_values("./folders.env").items()
}

FOLDER_A: str = ENV_V["folder_a"]
FOLDER_B: str = ENV_V["folder_b"]

# Size of chunks read into memory (64KB is optimal for most disks)
CHUNK_SIZE = 65536
# ========================================================


def pwrite(wf: TextIOWrapper, string: str) -> None:
    print(string)
    wf.write(string + "\n")


def compute_checksums(file_path) -> dict[str, str]:
    """
    Computes both MD5 and SHA-256 hashes for a given file in chunks.
    Releases the GIL during chunk updates for true multithreaded performance.
    """
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()

    try:
        with open(file=file_path, mode="rb") as f:
            while True:
                data: bytes = f.read(CHUNK_SIZE)
                if not data:
                    break
                md5_hash.update(data)
                sha256_hash.update(data)
        return {
            "md5": md5_hash.hexdigest(),
            "sha256": sha256_hash.hexdigest(),
            "error": "",
        }
    except Exception as e:
        return {"md5": "", "sha256": "", "error": str(e)}


def scan_and_hash_folder(base_folder) -> dict[str, dict[str, str]]:
    """
    Recursively scans a folder and hashes all files using a thread pool.
    Returns a dictionary mapping relative paths to their hashes.
    """
    file_tasks = []

    # 1. Gather all files in the directory recursively
    for root, _, files in os.walk(base_folder):
        for file in files:
            full_path: str = os.path.join(root, file)
            # We track the relative path to compare files across different folder structures
            rel_path: str = os.path.relpath(full_path, base_folder)
            file_tasks.append((rel_path, full_path))

    # If folder is empty
    if not file_tasks:
        return {}

    # 2. Hash files concurrently (one thread per file up to system limits)
    # ThreadPoolExecutor automatically scales based on the number of files and CPU cores
    results: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor() as executor:
        # Submit all tasks to the thread pool
        future_to_file = {
            executor.submit(compute_checksums, full_path): rel_path
            for rel_path, full_path in file_tasks
        }

        for future in future_to_file:
            rel_path = future_to_file[future]
            results[rel_path] = future.result()

    return results


def compare_folders():
    print(f"Scanning FOLDER A: {FOLDER_A}")
    hashes_a: dict[str, dict[str, str]] = scan_and_hash_folder(FOLDER_A)

    print(f"Scanning FOLDER B: {FOLDER_B}")
    hashes_b: dict[str, dict[str, str]] = scan_and_hash_folder(FOLDER_B)

    # Track the differences
    only_in_a: list[str] = []
    only_in_b: list[str] = []
    mismatched: list[dict[str, str]] = []
    identical: list[str] = []
    errors: list[tuple[str, str]] = []

    # Combine all unique relative paths
    all_rel_paths: set[str] = set(hashes_a.keys()).union(set(hashes_b.keys()))

    for rel_path in all_rel_paths:
        file_a: dict[str, str] | None = hashes_a.get(rel_path)
        file_b: dict[str, str] | None = hashes_b.get(rel_path)

        if file_a is None:
            file_a = {}
        if file_b is None:
            file_b = {}

        # Check for access errors first
        if (file_a and file_a["error"]) or (file_b and file_b["error"]):
            fae: str | None = file_a.get("error")
            fae = fae if fae else ""

            fbe: str | None = file_b.get("error")
            fbe = fbe if fbe else ""

            errors.append((rel_path, fae if file_a else fbe))
            continue

        if file_a and not file_b:
            only_in_a.append(rel_path)
        elif file_b and not file_a:
            only_in_b.append(rel_path)
        else:
            # Both exist, compare their checksums
            if file_a["md5"] == file_b["md5"] and file_a["sha256"] == file_b["sha256"]:
                identical.append(rel_path)
            else:
                mismatched.append(
                    {
                        "path": rel_path,
                        "a_md5": file_a["md5"],
                        "b_md5": file_b["md5"],
                        "a_sha256": file_a["sha256"],
                        "b_sha256": file_b["sha256"],
                    }
                )

    # ================= OUTPUT SAVE =================
    with open(file="./results.txt", mode="w", encoding="utf-8") as wf:
        pwrite(wf, "\n" + "=" * 50)
        pwrite(wf, " COMPARISON SUMMARY")
        pwrite(wf, "=" * 50)
        pwrite(wf, f"Identical Files: {len(identical)}")
        pwrite(wf, f"Mismatched Files (Modified): {len(mismatched)}")
        pwrite(wf, f"Only in Folder A: {len(only_in_a)}")
        pwrite(wf, f"Only in Folder B: {len(only_in_b)}")
        if errors:
            pwrite(wf, f"Files with Read Errors: {len(errors)}")

        if mismatched:
            pwrite(wf, "\n--- MISMATCHED FILES (Contents differ) ---")
            for item in mismatched:
                pwrite(wf, f"\nFile: {item['path']}")
                pwrite(
                    wf,
                    f"  Folder A | MD5: {item['a_md5'][:8]}... | SHA256: {item['a_sha256'][:8]}...",
                )
                pwrite(
                    wf,
                    f"  Folder B | MD5: {item['b_md5'][:8]}... | SHA256: {item['b_sha256'][:8]}...",
                )

        if only_in_a:
            pwrite(wf, "\n--- ONLY IN FOLDER A ---")
            for f in only_in_a:
                pwrite(wf, f"  + {f}")

        if only_in_b:
            pwrite(wf, "\n--- ONLY IN FOLDER B ---")
            for f in only_in_b:
                pwrite(wf, f"  + {f}")

        if errors:
            pwrite(wf, "\n--- ERRORS ENCOUNTERED ---")
            for path, err in errors:
                pwrite(wf, f"  Error reading {path}: {err}")


if __name__ == "__main__":
    compare_folders()
