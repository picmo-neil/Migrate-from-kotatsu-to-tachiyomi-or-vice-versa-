
# Manga Migration Kit (Kotatsu <-> Tachiyomi)

This repository contains an intelligent workflow to convert backup files between **Kotatsu** and **Tachiyomi/Mihon**.

## Features
*   **Bi-Directional**: Automatically detects input format.
*   **Kotatsu to Tachiyomi**: Upload `Backup.zip` → Get `.tachibk`
*   **Tachiyomi to Kotatsu**: Upload `Backup.tachibk` → Get `.zip`

## 🛠️ How it works
This repository uses a **GitHub Action** to:
1.  Install **Protocol Buffers** compiler (`protoc`).
2.  Compile the `schema.proto` into a Python class on the fly.
3.  Execute `main.py` to convert your backup with mathematical precision.

## Usage
1.  **Fork/Copy this Repo**.
2.  **Upload your Backup**:
    *   If converting **Kotatsu** -> Name it `Backup.zip`.
    *   If converting **Tachiyomi** -> Name it `Backup.tachibk`.
3.  **Run**: Actions -> **Universal Convert**.
4.  **Download**: The artifact `converted_backup`.
