# -*- coding: utf-8 -*-
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog


class TermiusModifier:
    @property
    def _backup_path(self):
        return os.path.join(self.termius_path, "app.asar.bak")

    @property
    def _original_path(self):
        return os.path.join(self.termius_path, "app.asar")

    @property
    def _app_dir(self):
        return os.path.join(self.termius_path, "app")

    def __init__(self, termius_path):
        self.termius_path = termius_path
        self.files_cache = {}
        self.loaded_rules = []
        self.applied_rules = set()

    def load_rules(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, "trial.txt")
        
        try:
            if content := read_file(file_path):
                self.loaded_rules.extend(content)
        except Exception as e:
            logging.error(f"Error loading trial.txt: {e}")
            sys.exit(1)

    def decompress_asar(self):
        cmd = f'asar extract {self._original_path} {self._app_dir}'
        run_command(cmd, shell=True)

    def pack_to_asar(self):
        cmd = f'asar pack {self._app_dir} {self._original_path} --unpack-dir "{{node_modules/@termius,out}}"'
        run_command(cmd, shell=True)

    def restore_backup(self):
        if not os.path.exists(self._backup_path):
            logging.info("Backup file not found, skip backup restore.")
            return

        shutil.copy(self._backup_path, self._original_path)
        logging.info("Restored from backup.")

    def create_backup(self):
        if not os.path.exists(self._backup_path):
            shutil.copy(self._original_path, self._backup_path)
            logging.info("Created initial backup.")

    def manage_workspace(self):
        self.create_backup()
        self.clean_workspace()

    def clean_workspace(self):
        self.restore_backup()
        # 清理
        if os.path.exists(self._app_dir):
            safe_rmtree(self._app_dir)
            logging.debug("Cleaned app directory.")

    def load_files(self):
        code_files = self.collect_code_files()
        for file in code_files:
            if os.path.exists(file):
                self.files_cache[file] = read_file(file, strip_empty=False)

    def replace_content(self, file_content):
        if not file_content:
            return file_content

        for line in self.loaded_rules:
            try:
                if is_comment_line(line):
                    self.applied_rules.add(line)
                    continue
                old_val, new_val = parse_replace_rule(line)
                original_content = file_content
                if is_regex_pattern(old_val):
                    pattern = re.compile(old_val[1:-1])
                    file_content = pattern.sub(new_val, file_content)
                else:
                    file_content = file_content.replace(old_val, new_val)

                if original_content != file_content:
                    self.applied_rules.add(line)

            except ValueError as e:
                logging.error(f"Skipping invalid rule: {line} → {str(e)}")
            except re.error as e:
                logging.error(f"Regex error: {line} → {str(e)}")

        return file_content

    def replace_rules(self):
        logging.info("Starting replacement...")
        for file_path in self.files_cache:
            self.files_cache[file_path] = self.replace_content(self.files_cache[file_path])
        logging.info("Replacement completed.")

    def write_files(self):
        logging.info("Starting writing...")
        for file_path, content in self.files_cache.items():
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)
        logging.info("Writing completed.")

    def collect_code_files(self):
        prefix_links = [
            os.path.join(self._app_dir, "background-process", "assets"),
            os.path.join(self._app_dir, "ui-process", "assets"),
            os.path.join(self._app_dir, "main-process"),
        ]
        code_files = []
        for prefix in prefix_links:
            for root, _, files in os.walk(prefix):
                code_files.extend([os.path.join(root, f) for f in files if f.endswith(".js")])
        return code_files

    def apply_changes(self):
        start_time = time.monotonic()
        self.manage_workspace()
        self.decompress_asar()
        self.load_rules()
        self.load_files()
        self.replace_rules()
        self.write_files()
        self.pack_to_asar()
        apply_macos_fix()
        elapsed = time.monotonic() - start_time
        logging.info(f"Replacement done in {elapsed:.2f} seconds.")

        logging.info(f"Rules applied: {len(self.applied_rules)}/{len(self.loaded_rules)}")
        unmatched_rules = list(filter(lambda x: x not in self.applied_rules, self.loaded_rules))
        if unmatched_rules:
            if len(unmatched_rules) > 3:
                logging.warning(f"Found {len(unmatched_rules)} unmatched rules. Check debug log for details.")
            rules_list = "\n".join([f"{i + 1:>4}. {rule}" for i, rule in enumerate(unmatched_rules)])
            logging.debug(f"Unmatched rules ({len(unmatched_rules)}):\n{rules_list}")
        else:
            logging.debug("All rules matched.")


def run_command(cmd, shell=False):
    if isinstance(cmd, list):
        logging.info(f"Running command: {' '.join(cmd)}")
    else:
        logging.info(f"Running command: {cmd}")
    try:
        subprocess.run(cmd, shell=shell, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)


def _handle_remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def safe_rmtree(path):
    if not os.path.exists(path):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_handle_remove_readonly)
    else:
        shutil.rmtree(path, onerror=_handle_remove_readonly)


def read_file(file_path, strip_empty=True):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return [line.rstrip("\r\n") for line in file if line.strip()] if strip_empty else file.read()
    except Exception as e:
        logging.error(f"Read error: {file_path} - {e}")
        sys.exit(1)


def is_comment_line(line):
    return line.strip().startswith("#")


def is_regex_pattern(s):
    return len(s) > 1 and s.startswith("/") and s.endswith("/") and "//" not in s


def parse_replace_rule(rule):
    if "|" not in rule:
        raise ValueError("Invalid replacement rule format.")
    return rule.split("|", 1)


def is_valid_path(path):
    return path and os.path.isdir(path)


def check_asar_existence(path):
    return os.path.exists(os.path.join(path, "app.asar"))


def check_asar_installed():
    run_command("asar --version", shell=True)


def select_directory(title):
    try:
        root = tk.Tk()
        root.withdraw()
        selected_path = filedialog.askdirectory(title=title)
        root.destroy()
        return selected_path if is_valid_path(selected_path) else None
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        sys.exit(1)


def is_macos():
    return platform.system() == 'Darwin'


def apply_macos_fix():
    if is_macos():
        logging.info("Applying macOS fix...")
        script_path = "./osxfix.sh"
        run_command(["chmod", "+x", script_path])
        run_command(script_path)
        logging.info("MacOS fix applied.")


def get_termius_path():
    default_paths = {
        "Windows": lambda: os.path.join(os.getenv("LOCALAPPDATA"), "Programs", "Termius", "resources"),
        "Darwin": lambda: "/Applications/Termius.app/Contents/Resources",
        "Linux": lambda: "/opt/Termius/resources"
    }
    system = platform.system()
    path_generator = default_paths.get(system)

    if path_generator:
        termius_path = path_generator()
    else:
        logging.error(f"Unsupported OS: {system}")
        sys.exit(1)
        
    if not check_asar_existence(termius_path):
        logging.warning(f"Termius app.asar file not found at: {os.path.join(termius_path, 'app.asar')}")
        logging.info("Please select the correct Termius folder.")
        termius_path = select_directory("Please select the Termius path containing app.asar.")
        if not termius_path or not check_asar_existence(termius_path):
            logging.error("Valid Termius app.asar file not found. Exiting.")
            sys.exit(1)

    return termius_path


def main():
    logging.basicConfig(level='INFO', format="%(asctime)s - %(levelname)7s - %(message)s", force=True)
    
    logging.info("Running in trial mode...")
    
    check_asar_installed()
    termius_path = get_termius_path()
    modifier = TermiusModifier(termius_path)
    modifier.apply_changes()


if __name__ == "__main__":
    main()
