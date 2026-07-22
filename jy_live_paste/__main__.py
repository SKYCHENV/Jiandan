from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["import", "gui"], default="gui")
    args = parser.parse_args()

    if args.command == "import":
        from .importer import import_clipboard_image

        report = import_clipboard_image()
        print(f"已导入并预览：{report.image_path}")
        return

    from .status_gui import run_gui

    run_gui()


if __name__ == "__main__":
    main()
