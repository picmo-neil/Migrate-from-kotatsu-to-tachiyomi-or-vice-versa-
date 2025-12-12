
# Manga Migration Kit (Kotatsu <-> Tachiyomi)

This repository contains an intelligent workflow to convert backup files between **Kotatsu** and **Tachiyomi/Mihon**.

## Features
*   **Bi-Directional**: Automatically detects input format.
*   **Kotatsu to Tachiyomi**: Upload `Backup.zip` → Get `.tachibk`
*   **Tachiyomi to Kotatsu**: Upload `Backup.tachibk` → Get `.zip`

## How to use

1.  **Fork/Copy this Repo**.
2.  **Upload your Backup**:
    *   If converting **Kotatsu** -> Name it `Backup.zip`.
    *   If converting **Tachiyomi** -> Name it `Backup.tachibk`.
3.  **Run Workflow**:
    *   Go to **Actions** tab -> **Convert Backup** -> **Run workflow**.
4.  **Download Result**: Check the artifacts section of the run.

## Directory Structure

```
├── .github/workflows/migrate.yml
├── src
│   ├── index.js
│   └── schema.proto
├── .gitignore
├── package.json
├── README.md
└── Backup.zip (or Backup.tachibk)
```
