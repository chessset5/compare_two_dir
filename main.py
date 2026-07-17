import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dotenv import dotenv_values

# ================= GLOBAL CONFIGURATION =================
ENV_V: dict[str, str] = {k: v if v else "" for k, v in dotenv_values("./folders.env").items()}

FOLDER_A: str = ENV_V["folder1"]
FOLDER_B: str = ENV_V["folder2"]

# Size of chunks read into memory (64KB is optimal for most disks)
CHUNK_SIZE = 65536
# ========================================================


def compute_checksums(file_path):
    """
    Computes both MD5 and SHA-256 hashes for a given file in chunks.
    Releases the GIL during chunk updates for true multithreaded performance.
    """
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                md5_hash.update(data)
                sha256_hash.update(data)
        return {
            "md5": md5_hash.hexdigest(),
            "sha256": sha256_hash.hexdigest(),
            "error": None,
        }
    except Exception as e:
        return {"md5": None, "sha256": None, "error": str(e)}


def scan_and_hash_folder(base_folder):
    """
    Recursively scans a folder and hashes all files using a thread pool.
    Returns a dictionary mapping relative paths to their hashes.
    """
    file_tasks = []

    # 1. Gather all files in the directory recursively
    for root, _, files in os.walk(base_folder):
        for file in files:
            full_path = os.path.join(root, file)
            # We track the relative path to compare files across different folder structures
            rel_path = os.path.relpath(full_path, base_folder)
            file_tasks.append((rel_path, full_path))

    # If folder is empty
    if not file_tasks:
        return {}

    # 2. Hash files concurrently (one thread per file up to system limits)
    # ThreadPoolExecutor automatically scales based on the number of files and CPU cores
    results = {}
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
    hashes_a = scan_and_hash_folder(FOLDER_A)

    print(f"Scanning FOLDER B: {FOLDER_B}")
    hashes_b = scan_and_hash_folder(FOLDER_B)

    # Track the differences
    only_in_a = []
    only_in_b = []
    mismatched = []
    identical = []
    errors = []

    # Combine all unique relative paths
    all_rel_paths = set(hashes_a.keys()).union(set(hashes_b.keys()))

    for rel_path in all_rel_paths:
        file_a = hashes_a.get(rel_path)
        file_b = hashes_b.get(rel_path)

        # Check for access errors first
        if (file_a and file_a["error"]) or (file_b and file_b["error"]):
            errors.append(
                (rel_path, file_a.get("error") if file_a else file_b.get("error"))
            )
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

    # ================= OUTPUT RESULTS =================
    print("\n" + "=" * 50)
    print(" COMPARISON SUMMARY")
    print("=" * 50)
    print(f"Identical Files: {len(identical)}")
    print(f"Mismatched Files (Modified): {len(mismatched)}")
    print(f"Only in Folder A: {len(only_in_a)}")
    print(f"Only in Folder B: {len(only_in_b)}")
    if errors:
        print(f"Files with Read Errors: {len(errors)}")

    if mismatched:
        print("\n--- MISMATCHED FILES (Contents differ) ---")
        for item in mismatched:
            print(f"\nFile: {item['path']}")
            print(
                f"  Folder A | MD5: {item['a_md5'][:8]}... | SHA256: {item['a_sha256'][:8]}..."
            )
            print(
                f"  Folder B | MD5: {item['b_md5'][:8]}... | SHA256: {item['b_sha256'][:8]}..."
            )

    if only_in_a:
        print("\n--- ONLY IN FOLDER A ---")
        for f in only_in_a:
            print(f"  + {f}")

    if only_in_b:
        print("\n--- ONLY IN FOLDER B ---")
        for f in only_in_b:
            print(f"  + {f}")

    if errors:
        print("\n--- ERRORS ENCOUNTERED ---")
        for path, err in errors:
            print(f"  Error reading {path}: {err}")


if __name__ == "__main__":
    compare_folders()
