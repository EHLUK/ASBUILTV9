"""
As-Built Drawing Compiler — HPC HK2794
Streamlit web app — v3
"""

import os
import re
import tempfile
import shutil
from collections import Counter
from pathlib import Path

import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
ASSETS_DIR       = Path(__file__).parent / "assets"
BUNDLED_TEMPLATE = ASSETS_DIR / "E21369-EHL-XX-ZZ-RP-MM-000xxx.docx"
BUNDLED_STAMP    = ASSETS_DIR / "conformance_stamp.png"
APP_PASSWORD     = "HPC2794"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="As-Built Compiler — HK2794",
    page_icon="📐",
    layout="centered",
)

# ── Password gate ─────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("📐 As-Built Compiler — HK2794")
    st.markdown("---")
    pwd = st.text_input("Enter password to continue", type="password")
    if st.button("Login", type="primary"):
        if pwd == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

# ── Import compiler after auth (avoids startup crash if import fails) ─────────
try:
    from compiler import (
        extract_trn, match_drawings, render_and_stamp,
        build_docx, make_output_filename,
    )
    compiler_ok = True
except Exception as e:
    compiler_ok = False
    st.error(f"❌ Failed to load compiler: {e}")
    st.stop()

# ── Main app ──────────────────────────────────────────────────────────────────
st.title("📐 As-Built Drawing Compiler")
st.caption("HPC HK2794 · Exentec Hargreaves · Ductwork")
st.markdown("---")

# ── File uploads ──────────────────────────────────────────────────────────────
st.subheader("1 · Upload files")

col1, col2 = st.columns(2)

with col1:
    trn_file = st.file_uploader(
        "TRN PDF *(required)*",
        type=["pdf"],
        help="Technical Release Note — contains the ECS code table",
    )
    drawing_files = st.file_uploader(
        "Ductwork Drawing PDFs *(required)*",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload drawing PDFs one at a time to avoid memory limits.",
    )

with col2:
    if BUNDLED_TEMPLATE.exists():
        st.success("✓ Word template bundled")
        template_file = None
    else:
        template_file = st.file_uploader(
            "As-Built Word template (.docx) *(required)*",
            type=["docx"],
        )

    if BUNDLED_STAMP.exists():
        st.success("✓ Conformance stamp bundled")
        stamp_file = None
    else:
        stamp_file = st.file_uploader(
            "Conformance Stamp PNG *(required)*",
            type=["png"],
            help="Portrait red-border stamp image",
        )

# ── File size warning ─────────────────────────────────────────────────────────
if drawing_files:
    total_mb = sum(f.size for f in drawing_files) / 1_048_576
    if total_mb > 80:
        st.error(
            f"⚠️ {total_mb:.0f} MB uploaded — this may exceed the server memory limit. "
            f"Try uploading 1-2 PDFs at a time."
        )
    elif total_mb > 40:
        st.warning(
            f"⚠️ {total_mb:.0f} MB uploaded. Processing may take 3–5 minutes."
        )

st.markdown("---")

# ── Readiness ─────────────────────────────────────────────────────────────────
template_ready = BUNDLED_TEMPLATE.exists() or template_file is not None
stamp_ready    = BUNDLED_STAMP.exists()    or stamp_file    is not None

missing = []
if not trn_file:       missing.append("TRN PDF")
if not drawing_files:  missing.append("at least one drawing PDF")
if not template_ready: missing.append("Word template")
if not stamp_ready:    missing.append("conformance stamp PNG")

st.subheader("2 · Compile")
if missing:
    st.info(f"Still needed: {', '.join(missing)}")

run_btn = st.button(
    "▶  Build As-Built Document",
    disabled=bool(missing),
    type="primary",
)

# ── Run ───────────────────────────────────────────────────────────────────────
if run_btn and not missing:

    status_text  = st.empty()
    progress_bar = st.progress(0)

    def upd(msg, pct):
        status_text.info(f"⏳ {msg}")
        progress_bar.progress(int(pct))

    with tempfile.TemporaryDirectory() as tmp:
        try:
            upd("Saving uploaded files…", 2)

            trn_path = os.path.join(tmp, "trn.pdf")
            with open(trn_path, "wb") as f:
                f.write(trn_file.read())

            template_path = os.path.join(tmp, "template.docx")
            if BUNDLED_TEMPLATE.exists():
                shutil.copy2(BUNDLED_TEMPLATE, template_path)
            else:
                with open(template_path, "wb") as f:
                    f.write(template_file.read())

            stamp_path = os.path.join(tmp, "stamp.png")
            if BUNDLED_STAMP.exists():
                shutil.copy2(BUNDLED_STAMP, stamp_path)
            else:
                with open(stamp_path, "wb") as f:
                    f.write(stamp_file.read())

            drawing_paths = []
            for df in drawing_files:
                dp = os.path.join(tmp, df.name)
                with open(dp, "wb") as f:
                    f.write(df.read())
                drawing_paths.append(dp)

            upd("Extracting ECS codes from TRN…", 8)
            trn_data     = extract_trn(trn_path)
            ecs_codes    = trn_data["ecs_codes"]
            ecs_ductbook = trn_data["ecs_ductbook"]
            delivery_ref = trn_data["delivery_ref"]

            if not ecs_codes:
                st.error("❌ No ECS codes found in the TRN. Check the file and try again.")
                st.stop()

            db_counts = Counter(ecs_ductbook.values())
            upd(f"Found {len(ecs_codes)} ECS codes across {len(db_counts)} ductbook(s)", 18)

            n_pdfs = len(drawing_paths)
            def scan_prog(msg):
                m = re.search(r'\((\d+)/', msg)
                i = int(m.group(1)) if m else 1
                upd(msg, 18 + int(i / n_pdfs * 22))

            matches, not_found, duplicates = match_drawings(
                ecs_codes, ecs_ductbook, drawing_paths, progress=scan_prog
            )
            upd(f"Matched {len(matches)}/{len(ecs_codes)} drawings", 40)

            total = len(matches)
            def stamp_prog(msg):
                m = re.search(r'(\d+)/', msg)
                i = int(m.group(1)) if m else 1
                upd(msg, 42 + int(i / total * 38) if total else 42)

            stamped_paths, failed = render_and_stamp(
                matches, stamp_path, tmp, progress=stamp_prog
            )

            if stamped_paths:
                first_path = next(iter(stamped_paths.values()))
                with st.expander("🔍 Stamp position preview", expanded=True):
                    from PIL import Image as PILImage
                    img  = PILImage.open(first_path)
                    w, h = img.size
                    crop = img.crop((0, int(h * 0.55), w, h))
                    st.image(crop, caption=f"Title block preview", use_container_width=True)

            upd(f"Stamped {len(stamped_paths)} drawings", 82)
            upd("Building Word document…", 88)

            output_filename = make_output_filename(trn_data)
            output_path     = os.path.join(tmp, output_filename)

            build_docx(
                template_path, trn_data, matches,
                stamped_paths, output_path, tmp,
                progress=lambda m: upd(m, 93)
            )

            upd("Done!", 100)
            status_text.success("✅ As-Built document compiled successfully")

            st.markdown("---")
            st.subheader("3 · Results")

            col_a, col_b, col_c = st.columns(3)
            col_a.metric("ECS codes in TRN",  len(ecs_codes))
            col_b.metric("Drawings matched",  len(matches))
            col_c.metric("Drawings embedded", len(stamped_paths))

            if duplicates:
                lines = "\n".join(
                    f"• `{ecs}` in: {', '.join(Path(p).name for p in pdfs)}"
                    for ecs, pdfs in duplicates.items()
                )
                st.warning(f"⚠️ {len(duplicates)} duplicate ECS codes found:\n\n{lines}")

            if not_found:
                missing_db = Counter(ecs_ductbook.get(c, "unknown") for c in not_found)
                lines = "\n".join(
                    f"• `{db}.pdf` — {cnt} drawings"
                    for db, cnt in sorted(missing_db.items())
                )
                st.warning(f"⚠️ {len(not_found)} drawings not found:\n\n{lines}")

            if failed:
                lines = "\n".join(f"• `{ecs}` — {reason}" for ecs, reason in failed)
                st.error(f"❌ {len(failed)} drawing(s) failed to render:\n\n{lines}")

            matched_dbs = []
            for ecs in ecs_codes:
                db = ecs_ductbook.get(ecs)
                if db and db not in matched_dbs and ecs in stamped_paths:
                    matched_dbs.append(db)

            if matched_dbs:
                st.markdown("**Appendices built (in TRN order):**")
                for i, db in enumerate(matched_dbs):
                    n = sum(1 for e in ecs_codes
                            if ecs_ductbook.get(e) == db and e in stamped_paths)
                    st.markdown(f"- Appendix {i+1}: `{db}` — {n} drawings")

            with open(output_path, "rb") as f:
                docx_bytes = f.read()

            st.download_button(
                label=f"⬇️  Download  {output_filename}",
                data=docx_bytes,
                file_name=output_filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
            )

        except Exception as e:
            status_text.error(f"❌ Error: {e}")
            import traceback
            st.code(traceback.format_exc())

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
col_f1, col_f2 = st.columns([4, 1])
col_f1.caption("Exentec Hargreaves · HPC HK2794 · As-Built Compiler v3")
if col_f2.button("Logout", use_container_width=True):
    st.session_state.authenticated = False
    st.rerun()
