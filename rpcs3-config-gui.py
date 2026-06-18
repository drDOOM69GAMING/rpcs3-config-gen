#!/tmp/rpcs3_venv/bin/python3
import os, sys, io, threading, queue
from tkinter import (
    Tk, Frame, Button, Label, Text, Scrollbar, filedialog,
    messagebox, LEFT, RIGHT, BOTH, VERTICAL, END, N, S, E, W
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpcs3_config_generator as core

CUSTOM_CONFIGS_DIR = os.path.expanduser("~/.config/rpcs3/custom_configs")

class StdoutCapture(io.StringIO):
    def __init__(self, log_func):
        super().__init__()
        self.log_func = log_func
    def write(self, s):
        if s.strip():
            self.log_func(s.rstrip())
        super().write(s)
    def flush(self):
        pass

class RPCS3ConfigGUI:
    def __init__(self, root):
        self.root = root
        root.title("RPCS3 Config Generator")
        root.geometry("820x560")

        self.wiki_dir = ""
        self.installed_file = ""
        self.log_queue = queue.Queue()
        self.running = False

        self._build_ui()
        self._poll_log()
        # Try to auto-detect default paths
        self._auto_detect()

    def _auto_detect(self):
        search_dirs = [os.getcwd()]
        appimage = os.environ.get("APPIMAGE", "")
        if appimage:
            search_dirs.append(os.path.dirname(os.path.abspath(appimage)))
        search_dirs.append(os.path.expanduser("~/rpcs3-config-generator"))
        for d in search_dirs:
            wiki = os.path.join(d, "wiki_pages")
            inst = os.path.join(d, "Installed_within_rpcs3")
            if not self.wiki_dir and os.path.isdir(wiki):
                self.wiki_dir = wiki
                self.wiki_label.config(text=wiki, fg="#000")
            if not self.installed_file and os.path.isfile(inst):
                self.installed_file = inst
                self.installed_label.config(text=inst, fg="#000")
        self._update_config_count()

    def _build_ui(self):
        main = Frame(self.root, padx=12, pady=12)
        main.pack(fill=BOTH, expand=True)

        f1 = Frame(main)
        f1.pack(fill="x", pady=(0, 6))
        Label(f1, text="Wiki Pages Folder:", width=18, anchor="w").pack(side=LEFT)
        self.wiki_label = Label(f1, text="(not set)", fg="#888", anchor="w")
        self.wiki_label.pack(side=LEFT, fill="x", expand=True, padx=6)
        Button(f1, text="Browse…", command=self._browse_wiki).pack(side=RIGHT)

        f2 = Frame(main)
        f2.pack(fill="x", pady=(0, 6))
        Label(f2, text="Installed Games File:", width=18, anchor="w").pack(side=LEFT)
        self.installed_label = Label(f2, text="(not set)", fg="#888", anchor="w")
        self.installed_label.pack(side=LEFT, fill="x", expand=True, padx=6)
        Button(f2, text="Browse…", command=self._browse_installed).pack(side=RIGHT)

        f3 = Frame(main)
        f3.pack(fill="x", pady=8)
        self.scan_btn = Button(f3, text="1. Scan Wiki", command=self._run_scan, bg="#89b4fa")
        self.scan_btn.pack(side=LEFT, padx=(0, 6), fill="x", expand=True)
        self.gen_btn = Button(f3, text="2. Generate Configs", command=self._run_generate, bg="#a6e3a1")
        self.gen_btn.pack(side=LEFT, padx=(0, 6), fill="x", expand=True)
        self.full_btn = Button(f3, text="Scan + Generate", command=self._run_full, bg="#f9e2af")
        self.full_btn.pack(side=LEFT, fill="x", expand=True)

        self.status = Label(main, text="Ready", relief="sunken", anchor="w", bg="#eee")
        self.status.pack(fill="x", pady=(4, 0))

        f4 = Frame(main)
        f4.pack(fill=BOTH, expand=True, pady=(6, 0))
        self.log = Text(f4, wrap="word", state="disabled", font=("Consolas", 10), bg="#1e1e2e", fg="#cdd6f4")
        scroll = Scrollbar(f4, orient=VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side=RIGHT, fill="y")
        self.log.pack(fill=BOTH, expand=True)
        self.log.tag_config("ok", foreground="#a6e3a1")
        self.log.tag_config("err", foreground="#f38ba8")
        self.log.tag_config("info", foreground="#89b4fa")
        self.log.tag_config("bold", font=("Consolas", 10, "bold"))

        self.cfg_label = Label(main, text="", anchor="w", fg="#555")
        self.cfg_label.pack(fill="x")
        self._update_config_count()

    def _browse_wiki(self):
        d = filedialog.askdirectory(title="Select wiki_pages folder")
        if d:
            self.wiki_dir = d
            self.wiki_label.config(text=d, fg="#000")

    def _browse_installed(self):
        f = filedialog.askopenfilename(
            title="Select Installed_within_rpcs3 file",
            filetypes=[("All files", "*")]
        )
        if f:
            self.installed_file = f
            self.installed_label.config(text=f, fg="#000")

    def _log(self, msg, tag=None):
        self.log_queue.put((msg, tag))

    def _poll_log(self):
        while not self.log_queue.empty():
            msg, tag = self.log_queue.get_nowait()
            self.log.configure(state="normal")
            self.log.insert(END, msg + "\n", tag or ())
            self.log.see(END)
            self.log.configure(state="disabled")
        self.root.after(100, self._poll_log)

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for btn in (self.scan_btn, self.gen_btn, self.full_btn):
            btn.configure(state=state)
        self.running = busy
        self.root.update()

    def _run_scan(self):
        if not self.wiki_dir:
            messagebox.showwarning("Missing", "Select your wiki_pages folder first.")
            return
        if not self.installed_file:
            messagebox.showwarning("Missing", "Select your Installed_within_rpcs3 file first.")
            return
        self._set_busy(True)
        self.log.configure(state="normal"); self.log.delete("1.0", END); self.log.configure(state="disabled")
        self.status.config(text="Scanning wiki pages…")
        self._log("=== Scan: Wiki → Database ===", "bold")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        cap = StdoutCapture(self._log)
        old = sys.stdout
        sys.stdout = cap
        try:
            core.cmd_scan(force_serials=None, local_dir=self.wiki_dir, installed_list_path=self.installed_file)
            self._log("✅ Scan complete.", "ok")
        except Exception as e:
            self._log(f"❌ Error: {e}", "err")
        finally:
            sys.stdout = old
        self._set_busy(False)
        self.root.after(0, lambda: self.status.config(text="Scan done."))
        self.root.after(0, self._update_config_count)

    def _run_generate(self):
        if not self.installed_file:
            messagebox.showwarning("Missing", "Select your Installed_within_rpcs3 file first.")
            return
        self._set_busy(True)
        self.log.configure(state="normal"); self.log.delete("1.0", END); self.log.configure(state="disabled")
        self.status.config(text="Generating configs…")
        self._log("=== Generate: Database → Configs ===", "bold")
        threading.Thread(target=self._do_generate, daemon=True).start()

    def _do_generate(self):
        cap = StdoutCapture(self._log)
        old = sys.stdout
        sys.stdout = cap
        try:
            core.cmd_generate(force=True, only_missing=False, specific_serials=None, installed_list_path=self.installed_file)
            self._log("✅ Generate complete.", "ok")
        except Exception as e:
            self._log(f"❌ Error: {e}", "err")
        finally:
            sys.stdout = old
        self._set_busy(False)
        self.root.after(0, lambda: self.status.config(text="Generate done."))
        self.root.after(0, self._update_config_count)

    def _run_full(self):
        if not self.wiki_dir:
            messagebox.showwarning("Missing", "Select your wiki_pages folder first.")
            return
        if not self.installed_file:
            messagebox.showwarning("Missing", "Select your Installed_within_rpcs3 file first.")
            return
        self._set_busy(True)
        self.log.configure(state="normal"); self.log.delete("1.0", END); self.log.configure(state="disabled")
        self.status.config(text="Scanning + Generating…")
        self._log("=== Full: Scan → Database → Configs ===", "bold")
        threading.Thread(target=self._do_full, daemon=True).start()

    def _do_full(self):
        cap = StdoutCapture(self._log)
        old = sys.stdout
        sys.stdout = cap
        try:
            core.cmd_scan(force_serials=None, local_dir=self.wiki_dir, installed_list_path=self.installed_file)
            core.cmd_generate(force=True, only_missing=False, specific_serials=None, installed_list_path=self.installed_file)
            self._log("✅ Full run complete.", "ok")
        except Exception as e:
            self._log(f"❌ Error: {e}", "err")
        finally:
            sys.stdout = old
        self._set_busy(False)
        self.root.after(0, lambda: self.status.config(text="Done."))
        self.root.after(0, self._update_config_count)

    def _update_config_count(self):
        count = 0
        if os.path.isdir(CUSTOM_CONFIGS_DIR):
            count = len([f for f in os.listdir(CUSTOM_CONFIGS_DIR) if f.startswith("config_") and f.endswith(".yml")])
        self.cfg_label.config(text=f"Configs generated: {count}")

def main():
    # If CLI args given, run in terminal mode
    if len(sys.argv) > 1:
        old = sys.argv
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--gui"]
        core.main()
        sys.argv = old
        return
    root = Tk()
    RPCS3ConfigGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
