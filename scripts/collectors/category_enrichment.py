"""品类数据同步: 从 GlobalAlpha Compass 仓库拉取最新的建材与房地产 L2 品类数据
运行: python scripts/collectors/category_enrichment.py
"""
import json, os, subprocess, shutil, tempfile
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data"
CAT_DIR = DATA_DIR / "categories" / "建材与房地产"
TAXONOMY_FILE = DATA_DIR / "taxonomy.json"

COMPASS_REPO = "https://github.com/danniallcc-creator/globalalpha-compass.git"
COMPASS_CAT_DIR = "data/categories/建材与房地产"


def log(msg):
    print(f"[category_enrichment] {msg}")


def clone_compass_sparse():
    """Shallow clone compass repo, only checkout the target directory."""
    tmp = Path(tempfile.mkdtemp(prefix="compass_"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none",
             "--sparse", COMPASS_REPO, str(tmp / "repo")],
            capture_output=True, text=True, timeout=120
        )
        repo_dir = tmp / "repo"
        subprocess.run(
            ["git", "sparse-checkout", "set", COMPASS_CAT_DIR],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=30
        )
        src = repo_dir / COMPASS_CAT_DIR
        if src.exists():
            return src
        # Fallback: full clone if sparse fails
        log("Sparse checkout failed, trying full clone...")
        shutil.rmtree(str(tmp), ignore_errors=True)
        return full_clone()
    except Exception as e:
        log(f"Clone error: {e}")
        return full_clone()


def full_clone():
    """Full shallow clone as fallback."""
    tmp = Path(tempfile.mkdtemp(prefix="compass_"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", COMPASS_REPO, str(tmp / "repo")],
            capture_output=True, text=True, timeout=180
        )
        src = tmp / "repo" / COMPASS_CAT_DIR
        if src.exists():
            return src
        log("ERROR: Compass category directory not found")
        return None
    except Exception as e:
        log(f"Full clone error: {e}")
        return None


def sync_categories(src_dir):
    """Copy L2 JSON files from compass to bm-journal.

    Always refresh `last_updated` on the destination so that the exported
    PDF footer reflects the current journal build date, even when Compass
    upstream content has not changed this week.
    """
    CAT_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    updated_slugs = {}
    today = datetime.now().strftime("%Y-%m-%d")

    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".json"):
            continue
        src_file = src_dir / fn
        dst_file = CAT_DIR / fn

        try:
            data = json.loads(src_file.read_text(encoding="utf-8"))
            slug = fn.replace(".json", "")
            name_cn = data.get("name_cn", "")

            # Only copy if file doesn't exist or content changed
            if dst_file.exists():
                existing = json.loads(dst_file.read_text(encoding="utf-8"))
                if existing.get("dynamic_insight") == data.get("dynamic_insight") and \
                   existing.get("export_data") == data.get("export_data"):
                    # 内容未变: 仍需刷新 last_updated 让期刊 PDF 底部与本周同步
                    existing["last_updated"] = today
                    if not existing.get("data_source") or existing.get("data_source") == "merged_existing":
                        existing["data_source"] = "compass_sync"
                    dst_file.write_text(
                        json.dumps(existing, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    updated_slugs[name_cn] = slug
                    copied += 1
                    continue

            # 内容变化: 用 Compass 最新数据 + 本地当日日期戳
            data["last_updated"] = today
            data["data_source"] = "compass_sync"

            # Write to destination
            dst_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            updated_slugs[name_cn] = slug
            copied += 1
        except Exception as e:
            log(f"  Skip {fn}: {e}")

    return copied, updated_slugs


def update_taxonomy(updated_slugs):
    """Add l2_slug to taxonomy.json for matching categories."""
    if not TAXONOMY_FILE.exists():
        log("taxonomy.json not found, skipping taxonomy update")
        return 0

    tax = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
    cats = tax.get("categories", {})
    matched = 0

    for cn, slug in updated_slugs.items():
        if cn in cats:
            if cats[cn].get("l2_slug") != slug:
                cats[cn]["l2_slug"] = slug
                matched += 1
        else:
            # Category exists in Compass but not in taxonomy - we don't add
            # (taxonomy is maintained separately)
            pass

    if matched > 0:
        TAXONOMY_FILE.write_text(
            json.dumps(tax, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    return matched


def cleanup(tmp_dir):
    """Remove temp directory."""
    if tmp_dir and tmp_dir.exists():
        shutil.rmtree(str(tmp_dir.parent) if "repo" in str(tmp_dir) else str(tmp_dir),
                      ignore_errors=True)


def main():
    log(f"Starting category enrichment: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Clone compass
    src_dir = clone_compass_sparse()
    if not src_dir:
        log("ERROR: Could not access Compass repository")
        return

    tmp_root = Path(str(src_dir).split("/repo")[0])

    try:
        # Sync files
        copied, slugs = sync_categories(src_dir)
        log(f"Synced {copied} category files")

        # Update taxonomy
        tax_matched = update_taxonomy(slugs)
        log(f"Updated {tax_matched} taxonomy entries with l2_slug")

        # Summary
        total = len(list(CAT_DIR.glob("*.json"))) if CAT_DIR.exists() else 0
        log(f"Total category files: {total}")
        log("Category enrichment complete")
    finally:
        cleanup(tmp_root)


if __name__ == "__main__":
    main()
