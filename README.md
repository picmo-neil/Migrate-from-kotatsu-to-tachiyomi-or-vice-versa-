
# Manga Migration Kit (Doki/Kotatsu to Tachiyomi/Mihon)


## 🛠️ How it works
This repository uses a **GitHub Action** to:
1.  Install **Protocol Buffers** compiler (`protoc`).
2.  Compile the `schema.proto` into a Python class on the fly.
3.  Execute `main.py` to convert your backup with mathematical precision.

## Usage
1.  **Fork/Copy this Repo**.
2.  **Upload your Backup**:
3.  **Run**: Actions -> **Universal Convert**.
4.  **Download**: The artifact `converted_backup`.
