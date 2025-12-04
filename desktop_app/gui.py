import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from io import BytesIO

from .config import (
    ADMIN_ID,
    APP_CONFIG,
    BOT_TOKEN,
    CUSTOMER_EMAIL,
    IS_TEST,
    MERCHANT_LOGIN,
    PASSWORD1,
    PASSWORD2,
    RESULT_PORT,
    SHOP_SNO,
    TAX,
    USER_CHAT_ID,
    apply_config_to_globals,
    save_config,
)
from .database import (
    get_last_payment,
    get_payments,
    get_recent_payments_for_order,
    insert_payment,
)
from .invoice import (
    build_qr_image_bytes,
    create_invoice_and_get_link,
    get_payment_state,
)
from .paths import LOGO_PATH
from .telegram_utils import send_qr_to_telegram

# ---------- Цвета/темы интерфейса ----------

COLOR_BG = "#111827"
COLOR_PRIMARY = "#0F172A"
COLOR_CARD_BG = "#020617"
COLOR_ACCENT = "#F59E0B"
COLOR_ACCENT_DARK = "#D97706"
COLOR_ENTRY_BG = "#020617"
COLOR_ENTRY_BORDER = "#1F2937"
COLOR_TABLE_BG = "#020617"
COLOR_TABLE_BORDER = "#1F2937"
COLOR_TABLE_HEADER_BG = "#111827"
COLOR_TABLE_HEADER_FG = "#E5E7EB"
COLOR_LABEL = "#E5E7EB"
COLOR_MUTED = "#9CA3AF"


class App(tk.Tk):
    def __init__(self, cfg: dict):
        super().__init__()
        self.title("BONJOUR — Robokassa Desktop")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        self.configure(bg=COLOR_BG)

        self.cfg = cfg
        self.items: list[dict] = []
        self._settings_window: tk.Toplevel | None = None

        try:
            self.iconphoto(False, tk.PhotoImage(file=str(LOGO_PATH)))
        except Exception:
            pass

        self.style = ttk.Style(self)
        self._init_styles()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        self.frame_main = ttk.Frame(self.notebook, padding=16)
        self.frame_payments = ttk.Frame(self.notebook, padding=16)

        self.notebook.add(self.frame_main, text="Выставление счёта")
        self.notebook.add(self.frame_payments, text="Журнал платежей")

        self._build_main_tab()
        self._build_payments_tab()

        # Скрытые настройки: открываются только по Ctrl+Alt+S
        self.bind_all("<Control-Alt-s>", self.open_settings_window)

    # ---------- Стили ----------

    def _init_styles(self):
        style = self.style
        style.theme_use("clam")

        style.configure(
            ".",
            background=COLOR_BG,
            foreground=COLOR_LABEL,
            fieldbackground=COLOR_ENTRY_BG,
        )

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_CARD_BG, relief="solid", borderwidth=1)
        style.map("Card.TFrame", background=[("active", COLOR_CARD_BG)])

        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_LABEL, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=COLOR_MUTED, background=COLOR_BG, font=("Segoe UI", 9))

        style.configure(
            "Accent.TButton",
            background=COLOR_ACCENT,
            foreground="#111827",
            padding=8,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLOR_ACCENT_DARK), ("pressed", COLOR_ACCENT_DARK)],
        )

        style.configure(
            "TButton",
            background="#1F2937",
            foreground=COLOR_LABEL,
            padding=6,
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "TButton",
            background=[("active", "#374151"), ("pressed", "#374151")],
        )

        style.configure(
            "TEntry",
            fieldbackground=COLOR_ENTRY_BG,
            foreground=COLOR_LABEL,
            padding=4,
            bordercolor=COLOR_ENTRY_BORDER,
            lightcolor=COLOR_ENTRY_BORDER,
            darkcolor=COLOR_ENTRY_BORDER,
            insertcolor=COLOR_LABEL,
        )

        style.configure(
            "TNotebook",
            background=COLOR_BG,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background="#020617",
            foreground=COLOR_LABEL,
            padding=(16, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#111827"), ("!selected", "#020617")],
            foreground=[("selected", COLOR_LABEL)],
        )

        style.configure(
            "Treeview",
            background=COLOR_TABLE_BG,
            fieldbackground=COLOR_TABLE_BG,
            foreground=COLOR_LABEL,
            rowheight=26,
            bordercolor=COLOR_TABLE_BORDER,
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_TABLE_HEADER_BG,
            foreground=COLOR_TABLE_HEADER_FG,
            font=("Segoe UI", 9, "bold"),
        )

    # ---------- Вкладка "Выставление счёта" ----------

    def _build_main_tab(self):
        frame = self.frame_main

        left = ttk.Frame(frame, style="Card.TFrame", padding=16)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8), pady=0)

        right = ttk.Frame(frame, style="Card.TFrame", padding=16)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=0)

        # Левая часть — ввод заказа и позиций
        lbl_title = ttk.Label(left, text="Новый счёт на оплату", font=("Segoe UI Semibold", 14))
        lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(left, text="Номер заказа:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.order_entry = ttk.Entry(left, width=20)
        self.order_entry.grid(row=1, column=1, sticky="we", pady=4)
        left.grid_columnconfigure(1, weight=1)

        btn_load = ttk.Button(
            left,
            text="Загрузить услуги из программы",
            command=self.load_order_from_db,
        )
        btn_load.grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(left, text="Описание / услуги:").grid(row=2, column=0, sticky="ne", padx=(0, 8), pady=4)
        self.services_text = tk.Text(
            left,
            width=50,
            height=4,
            bg=COLOR_ENTRY_BG,
            fg=COLOR_LABEL,
            relief="flat",
            insertbackground=COLOR_LABEL,
            padx=6,
            pady=6,
        )
        self.services_text.grid(row=2, column=1, columnspan=2, sticky="we", pady=4)

        ttk.Label(left, text="Сумма к оплате, руб:").grid(row=3, column=0, sticky="e", padx=(0, 8), pady=4)
        self.amount_entry = ttk.Entry(left, width=20)
        self.amount_entry.grid(row=3, column=1, sticky="w", pady=4)

        # Позиции
        items_frame = ttk.LabelFrame(left, text="Позиции чека", padding=8)
        items_frame.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(12, 0))
        left.grid_rowconfigure(4, weight=1)

        self.items_listbox = tk.Listbox(
            items_frame,
            bg=COLOR_ENTRY_BG,
            fg=COLOR_LABEL,
            selectbackground=COLOR_ACCENT,
            selectforeground="#020617",
            relief="flat",
            activestyle="none",
            highlightthickness=0,
        )
        self.items_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(items_frame, orient=tk.VERTICAL, command=self.items_listbox.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.items_listbox.config(yscrollcommand=sb.set)

        btn_col = ttk.Frame(items_frame)
        btn_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        ttk.Button(btn_col, text="Добавить позицию", command=self.add_item_dialog).pack(fill=tk.X, pady=2)
        ttk.Button(btn_col, text="Изменить позицию", command=self.edit_selected_item).pack(fill=tk.X, pady=2)
        ttk.Button(btn_col, text="Удалить позицию", command=self.delete_selected_item).pack(fill=tk.X, pady=2)

        # Кнопка создания счёта
        btn_create = ttk.Button(
            left,
            text="Сформировать ссылку и QR для оплаты",
            style="Accent.TButton",
            command=self.generate_payment,
        )
        btn_create.grid(row=5, column=0, columnspan=3, sticky="we", pady=(12, 0))

        # Правая часть — проверка статуса, подсказки
        right.grid_columnconfigure(0, weight=1)

        ttk.Label(right, text="Проверка статуса оплаты", font=("Segoe UI Semibold", 12)).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        block = ttk.Frame(right)
        block.grid(row=1, column=0, sticky="we")
        block.grid_columnconfigure(1, weight=1)

        ttk.Label(block, text="Номер заказа:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.check_order_entry = ttk.Entry(block, width=20)
        self.check_order_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Button(
            block,
            text="Проверить статус оплаты онлайн",
            command=self.check_online_status,
        ).grid(row=0, column=2, padx=(8, 0), pady=4)

        hint = ttk.Label(
            right,
            text="После успешной оплаты Robokassa автоматически обновит статус.\n"
                 "Здесь можно запросить онлайн-статус по номеру заказа\n"
                 "(проверяются последние платежи по этому заказу).",
            style="Muted.TLabel",
            justify="left",
        )
        hint.grid(row=2, column=0, sticky="w", pady=(12, 0))

    # ---------- Работа с позициями ----------

    def update_items_listbox(self):
        self.items_listbox.delete(0, tk.END)
        for item in self.items:
            name = item.get("name", "")
            price = float(item.get("price", 0.0))
            qty = float(item.get("qty", 1))
            total = price * qty
            self.items_listbox.insert(
                tk.END,
                f"{name} — {qty:g} × {price:.2f} = {total:.2f} руб.",
            )

        base_total = sum(float(i.get("price", 0.0)) * float(i.get("qty", 1)) for i in self.items)
        self.base_total = base_total
        if not self.amount_entry.get().strip():
            self.amount_entry.delete(0, tk.END)
            self.amount_entry.insert(0, f"{base_total:.2f}")

        if self.items and not self.services_text.get("1.0", tk.END).strip():
            self.services_text.delete("1.0", tk.END)
            self.services_text.insert("1.0", "\n".join(i["name"] for i in self.items))

    def add_item_dialog(self):
        self._open_item_dialog()

    def edit_selected_item(self):
        selection = self.items_listbox.curselection()
        if not selection:
            messagebox.showinfo("Позиции", "Выберите позицию для изменения.")
            return
        index = selection[0]
        item = self.items[index]
        self._open_item_dialog(existing=item, index=index)

    def delete_selected_item(self):
        selection = self.items_listbox.curselection()
        if not selection:
            messagebox.showinfo("Позиции", "Выберите позицию для удаления.")
            return
        index = selection[0]
        del self.items[index]
        self.update_items_listbox()

    def _open_item_dialog(self, existing: dict | None = None, index: int | None = None):
        win = tk.Toplevel(self)
        win.title("Позиция чека")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Название:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        name_entry = ttk.Entry(frm, width=40)
        name_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(frm, text="Количество:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        qty_entry = ttk.Entry(frm, width=10)
        qty_entry.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="Цена за единицу:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        price_entry = ttk.Entry(frm, width=10)
        price_entry.grid(row=2, column=1, sticky="w", pady=4)

        frm.grid_columnconfigure(1, weight=1)

        if existing:
            name_entry.insert(0, existing.get("name", ""))
            qty_entry.insert(0, str(existing.get("qty", 1)))
            price_entry.insert(0, f"{existing.get('price', 0.0):.2f}")

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky="e")

        def on_save():
            name = name_entry.get().strip()
            qty_raw = qty_entry.get().strip()
            price_raw = price_entry.get().strip()

            if not name or not qty_raw or not price_raw:
                messagebox.showwarning("Позиция", "Заполните все поля.")
                return

            try:
                qty = float(qty_raw.replace(",", "."))
                price = float(price_raw.replace(",", "."))
            except Exception:
                messagebox.showerror("Позиция", "Некорректное количество или цена.")
                return

            if qty <= 0 or price <= 0:
                messagebox.showerror("Позиция", "Количество и цена должны быть больше 0.")
                return

            new_item = {
                "name": name[:128],
                "qty": qty,
                "price": price,
            }

            if existing is not None and index is not None:
                self.items[index] = new_item
            else:
                self.items.append(new_item)

            self.update_items_listbox()
            win.destroy()

        save_btn = ttk.Button(btns, text="Сохранить", command=on_save)
        save_btn.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_btn = ttk.Button(btns, text="Отмена", command=win.destroy)
        cancel_btn.pack(side=tk.RIGHT)

        win.wait_window()

    # ---------- Firebird ----------

    def load_order_from_db(self):
        order_number = self.order_entry.get().strip()
        if not order_number:
            messagebox.showwarning("Номер заказа", "Сначала введите номер заказа.")
            return

        db_path = APP_CONFIG.get("fb_db_path", "").strip()
        db_user = APP_CONFIG.get("fb_user", "").strip()
        db_password = APP_CONFIG.get("fb_password", "").strip()

        if not db_path or not db_user:
            messagebox.showwarning(
                "База данных",
                "Не указан путь к .fdb или логин в настройках.\n"
                "Откройте скрытые настройки (Ctrl+Alt+S) и заполните раздел Firebird.",
            )
            return

        try:
            import fdb  # type: ignore
        except ImportError:
            messagebox.showerror(
                "Firebird",
                "Не установлен драйвер Firebird для Python.\n\n"
                "Установите пакет:\n"
                "    pip install fdb",
            )
            return

        conn = None
        try:
            conn = fdb.connect(
                dsn=db_path,
                user=db_user,
                password=db_password,
                charset="WIN1251",
            )
            cur = conn.cursor()

            # Объединённый запрос: услуги + строки заказа, без истории/контрагента,
            # чтобы не было дублей
            sql = """
                SELECT
                    t1.name,
                    s.kredit
                FROM docs_order o1
                    INNER JOIN doc_order_services s
                        ON o1.id = s.doc_order_id
                    INNER JOIN tovars_tbl t1
                        ON s.tovar_id = t1.tovar_id
                    INNER JOIN docs d1
                        ON o1.doc_id = d1.doc_id
                WHERE d1.doc_num = ?

                UNION ALL

                SELECT
                    t2.name,
                    l.kredit
                FROM doc_order_lines l
                    INNER JOIN docs_order o2
                        ON l.doc_order_id = o2.id
                    INNER JOIN docs d2
                        ON o2.doc_id = d2.doc_id
                    INNER JOIN tovars_tbl t2
                        ON l.tovar_id = t2.tovar_id
                WHERE d2.doc_num = ?
            """
            cur.execute(sql, (order_number, order_number))
            rows = cur.fetchall()

            if not rows:
                messagebox.showinfo(
                    "Загрузка данных",
                    f"Заказ с номером {order_number} не найден в базе.",
                )
                return

            self.items = []
            for name, kredit in rows:
                try:
                    amount = float(kredit)
                except Exception:
                    continue
                item = {"name": str(name)[:128], "price": amount, "qty": 1}
                self.items.append(item)

            self.update_items_listbox()
            messagebox.showinfo(
                "Загрузка данных",
                f"Данные заказа {order_number} успешно загружены из базы.",
            )

        except Exception as e:
            messagebox.showerror("Firebird", f"Ошибка при обращении к базе:\n{e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    # ---------- Генерация платежа ----------

    def _get_current_amount(self) -> float:
        text = self.amount_entry.get().strip()
        if not text:
            return round(getattr(self, "base_total", 0.0), 2)
        raw = text.replace(",", ".")
        try:
            amount = float(raw)
        except Exception:
            raise ValueError("Сумма к оплате указана некорректно.")
        if amount <= 0:
            raise ValueError("Сумма к оплате должна быть больше 0.")
        return round(amount, 2)

    def generate_payment(self):
        order_number = self.order_entry.get().strip()
        if not order_number:
            messagebox.showwarning("Номер заказа", "Введите номер заказа.")
            return

        services = self.services_text.get("1.0", tk.END).strip()
        if not services:
            services = f"Оплата заказа {order_number}"

        try:
            amount = self._get_current_amount()
        except ValueError as e:
            messagebox.showerror("Сумма", str(e))
            return

        # Телеграм клиента/ID не спрашиваем — используем дефолт из настроек
        tg_username = ""
        tg_user_id = APP_CONFIG.get("user_chat_id") or 0

        try:
            payment_url, invoice_id = create_invoice_and_get_link(
                description=f"Заказ №{order_number}",
                amount=amount,
                item_name=services[:100],
            )
        except Exception as e:
            messagebox.showerror(
                "Создание счёта",
                f"Ошибка при создании счёта через Invoice API:\n{e}",
            )
            return

        try:
            insert_payment(
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                order_number=order_number,
                services=services,
                amount=amount,
                payment_url=payment_url,
                status="created",
                invoice_id=invoice_id if invoice_id is not None else None,
            )
        except Exception as e:
            messagebox.showerror(
                "База данных",
                f"Не удалось записать платёж в локальную базу:\n{e}",
            )
            return

        try:
            qr_bytes = build_qr_image_bytes(payment_url)
            send_qr_to_telegram(qr_bytes, payment_url, order_number)
        except Exception as e:
            print("[QR/TELEGRAM] Ошибка при отправке QR:", e)

        messagebox.showinfo(
            "Счёт создан",
            "Ссылка и QR-код успешно сформированы.\n"
            "QR-код и ссылка отправлены в Telegram.",
        )

    # ---------- Локальная проверка (оставлена как вспомогательная, без кнопки) ----------

    def check_payment_status(self):
        order_number = getattr(self, "check_order_entry", None)
        if order_number is None:
            messagebox.showerror("Статус оплаты", "Поле для ввода номера заказа не найдено.")
            return

        order_number = self.check_order_entry.get().strip()
        if not order_number:
            messagebox.showwarning(
                "Номер заказа", "Введите номер заказа для проверки."
            )
            return

        try:
            row = get_last_payment(order_number)
        except Exception as e:
            messagebox.showerror(
                "Статус оплаты", f"Не удалось обратиться к базе данных:\n{e}"
            )
            return

        if row is None:
            messagebox.showinfo(
                "Статус оплаты",
                f"Заказ {order_number} не найден в базе.",
            )
            return

        msg = (
            f"ID записи: {row['id']}\n"
            f"Создан: {row['created_at']}\n"
            f"Сумма: {row['amount']:.2f} руб.\n"
            f"Статус: {row['status']}\n"
            f"Покупатель: @{row['tg_username']}"
        )
        messagebox.showinfo("Статус оплаты", msg)

    # ---------- Онлайн-статус (OpStateExt, до 3 платежей) ----------

    def check_online_status(self):
        """Онлайн-статус платежа через Robokassa OpStateExt по последним 3 платежам заказа."""
        order_number = self.check_order_entry.get().strip()
        if not order_number:
            messagebox.showwarning(
                "Статус оплаты",
                "Введите номер заказа для проверки."
            )
            return

        # 1. Берём до 3 последних записей из локальной БД
        try:
            rows = get_recent_payments_for_order(order_number, limit=3)
        except Exception as e:
            messagebox.showerror(
                "Статус оплаты",
                f"Не удалось обратиться к базе данных:\n{e}",
            )
            return

        if not rows:
            messagebox.showinfo(
                "Статус оплаты",
                f"Заказ {order_number} не найден в локальной базе.",
            )
            return

        # Справочник кодов в человеко-читаемый статус
        state_map = {
            "5": "ожидает оплаты",
            "10": "отменён, деньги не получены",
            "20": "средства заморожены (HOLD)",
            "50": "деньги получены, зачисляются",
            "60": "отказ в зачислении / возврат",
            "80": "исполнение приостановлено",
            "100": "успешно оплачено",
        }

        def format_dt(dt_str: str | None) -> str:
            if not dt_str:
                return ""
            dt_str = dt_str.strip()
            # пробуем ISO-формат
            try:
                # отрезаем лишние микросекунды/зону, если что
                if dt_str.endswith("Z"):
                    dt_str_local = dt_str.replace("Z", "+00:00")
                else:
                    dt_str_local = dt_str
                dt = datetime.fromisoformat(dt_str_local)
                return dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                # пробуем формат локальной БД
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    return dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    return dt_str

        lines: list[str] = []
        lines.append(f"Заказ №{order_number}")
        lines.append("")

        any_online = False

        for idx, row in enumerate(rows, start=1):
            invoice_id = row["invoice_id"]
            local_created = row["created_at"] or ""
            local_amount = row["amount"] or 0.0

            if not invoice_id:
                status_text = "нет данных об онлайн-статусе (InvId не сохранён)"
                dt_text = format_dt(local_created)
            else:
                try:
                    info = get_payment_state_by_inv_id(int(invoice_id))
                    state_code = info.get("StateCode")
                    state_text = state_map.get(state_code or "", "статус не определён")
                    dt_text = format_dt(info.get("StateDate") or local_created)
                    status_text = state_text
                    any_online = True
                except Exception as e:
                    dt_text = format_dt(local_created)
                    status_text = f"ошибка при запросе статуса: {e}"

            amount_text = f"{float(local_amount):.2f} руб."
            dt_part = dt_text if dt_text else "дата не указана"

            lines.append(
                f"{idx}. Платёж: {dt_part} — {amount_text} — {status_text}"
            )

        if not any_online:
            lines.append("")
            lines.append("Онлайн-данные Robokassa недоступны (нет InvId или запрос завершился ошибкой).")

        messagebox.showinfo(
            "Статус оплаты",
            "\n".join(lines),
        )

    # ---------- Вкладка "Платежи" ----------

    def _build_payments_tab(self):
        frame = self.frame_payments

        top = ttk.Frame(frame)
        top.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top, text="Фильтр по номеру заказа:").pack(side=tk.LEFT)
        self.filter_entry = ttk.Entry(top, width=20)
        self.filter_entry.pack(side=tk.LEFT, padx=(8, 8))

        ttk.Button(
            top,
            text="Применить фильтр",
            command=self.refresh_payments,
        ).pack(side=tk.LEFT)

        ttk.Button(
            top,
            text="Экспортировать в CSV",
            command=self.export_payments_csv,
        ).pack(side=tk.RIGHT)

        columns = ("id", "created_at", "order_number", "amount", "status", "tg_username")

        self.tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            height=18,
        )
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.heading("id", text="ID")
        self.tree.heading("created_at", text="Создан")
        self.tree.heading("order_number", text="Заказ")
        self.tree.heading("amount", text="Сумма")
        self.tree.heading("status", text="Статус")
        self.tree.heading("tg_username", text="Покупатель")

        self.tree.column("id", width=50, anchor="center")
        self.tree.column("created_at", width=140, anchor="center")
        self.tree.column("order_number", width=100, anchor="w")
        self.tree.column("amount", width=100, anchor="e")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("tg_username", width=140, anchor="w")

        self.refresh_payments()

    def refresh_payments(self):
        flt = self.filter_entry.get().strip()

        for item in self.tree.get_children():
            self.tree.delete(item)

        rows = get_payments(flt)
        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["id"],
                    row["created_at"],
                    row["order_number"],
                    f"{row['amount']:.2f}",
                    row["status"],
                    row["tg_username"],
                ),
            )

    def export_payments_csv(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")],
            title="Сохранить платежи в CSV",
        )
        if not filename:
            return

        rows = get_payments("")
        import csv

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(
                    [
                        "ID",
                        "Создан",
                        "Номер заказа",
                        "Услуги",
                        "Сумма",
                        "Статус",
                        "TG username",
                        "TG user id",
                        "Ссылка на оплату",
                        "InvoiceID",
                    ]
                )
                for row in rows:
                    writer.writerow(
                        [
                            row["id"],
                            row["created_at"],
                            row["order_number"],
                            row["services"],
                            f"{row['amount']:.2f}",
                            row["status"],
                            row["tg_username"],
                            row["tg_user_id"],
                            row["payment_url"],
                            row["invoice_id"] if row["invoice_id"] is not None else "",
                        ]
                    )
            messagebox.showinfo("Экспорт", "Платежи успешно сохранены в CSV.")
        except Exception as e:
            messagebox.showerror("Экспорт", f"Ошибка при сохранении CSV:\n{e}")

    # ---------- Настройки (скрытое окно, вызывается по Ctrl+Alt+S) ----------

    def open_settings_window(self, event=None):
        # если уже открыто — поднимаем окно
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            return

        win = tk.Toplevel(self)
        win.title("Настройки")
        win.geometry("800x600")
        win.configure(bg=COLOR_BG)
        self._settings_window = win

        self.frame_settings = ttk.Frame(win, padding=16)
        self.frame_settings.pack(fill=tk.BOTH, expand=True)

        self._build_settings_tab()

        def on_close():
            self._settings_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

    def _build_settings_tab(self):
        frame = self.frame_settings

        lbl_title = ttk.Label(frame, text="Настройки", font=("Segoe UI Semibold", 14))
        lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        # Robokassa
        roboframe = ttk.LabelFrame(frame, text="Robokassa", padding=12)
        roboframe.grid(row=1, column=0, columnspan=3, sticky="we", pady=(0, 12))
        roboframe.grid_columnconfigure(1, weight=1)

        ttk.Label(roboframe, text="MerchantLogin:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.merchant_entry = ttk.Entry(roboframe, width=30)
        self.merchant_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Password1:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.password1_entry = ttk.Entry(roboframe, width=30, show="*")
        self.password1_entry.grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Password2:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.password2_entry = ttk.Entry(roboframe, width=30, show="*")
        self.password2_entry.grid(row=2, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Система налогообложения (SNO):").grid(
            row=3, column=0, sticky="e", padx=(0, 8), pady=4
        )
        self.sno_entry = ttk.Entry(roboframe, width=30)
        self.sno_entry.grid(row=3, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="НДС (Tax):").grid(row=4, column=0, sticky="e", padx=(0, 8), pady=4)
        self.tax_entry = ttk.Entry(roboframe, width=30)
        self.tax_entry.grid(row=4, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Email покупателя по умолчанию:").grid(
            row=5, column=0, sticky="e", padx=(0, 8), pady=4
        )
        self.email_entry = ttk.Entry(roboframe, width=30)
        self.email_entry.grid(row=5, column=1, sticky="we", pady=4)

        self.is_test_var = tk.IntVar(value=IS_TEST)
        ttk.Checkbutton(
            roboframe,
            text="Тестовый режим (для старых ссылок Robokassa)",
            variable=self.is_test_var,
        ).grid(row=6, column=1, sticky="w", pady=4)

        # Telegram
        tgframe = ttk.LabelFrame(frame, text="Telegram", padding=12)
        tgframe.grid(row=2, column=0, columnspan=3, sticky="we", pady=(0, 12))
        tgframe.grid_columnconfigure(1, weight=1)

        ttk.Label(tgframe, text="Bot Token:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.bot_token_entry = ttk.Entry(tgframe, width=40)
        self.bot_token_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(tgframe, text="Admin Telegram ID:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.admin_id_entry = ttk.Entry(tgframe, width=20)
        self.admin_id_entry.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(tgframe, text="Default user chat ID:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.user_chat_id_entry = ttk.Entry(tgframe, width=20)
        self.user_chat_id_entry.grid(row=2, column=1, sticky="w", pady=4)

        # ResultURL
        resframe = ttk.LabelFrame(frame, text="ResultURL-сервер", padding=12)
        resframe.grid(row=3, column=0, columnspan=3, sticky="we", pady=(0, 12))
        resframe.grid_columnconfigure(1, weight=1)

        ttk.Label(resframe, text="Порт ResultURL-сервера:").grid(
            row=0, column=0, sticky="e", padx=(0, 8), pady=4
        )
        self.result_port_entry = ttk.Entry(resframe, width=10)
        self.result_port_entry.grid(row=0, column=1, sticky="w", pady=4)

        # Firebird
        fbframe = ttk.LabelFrame(frame, text="Firebird (.fdb)", padding=12)
        fbframe.grid(row=4, column=0, columnspan=3, sticky="we", pady=(0, 12))
        fbframe.grid_columnconfigure(1, weight=1)

        ttk.Label(fbframe, text="Путь к базе (.fdb):").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.fb_path_entry = ttk.Entry(fbframe, width=40)
        self.fb_path_entry.grid(row=0, column=1, sticky="we", pady=4)

        def browse_fdb():
            path = filedialog.askopenfilename(
                title="Выберите базу Firebird",
                filetypes=[("Firebird DB", "*.fdb"), ("All files", "*.*")],
            )
            if path:
                self.fb_path_entry.delete(0, tk.END)
                self.fb_path_entry.insert(0, path)

        ttk.Button(fbframe, text="Обзор", command=browse_fdb).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(fbframe, text="Firebird user:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.fb_user_entry = ttk.Entry(fbframe, width=30)
        self.fb_user_entry.grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(fbframe, text="Firebird password:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.fb_password_entry = ttk.Entry(fbframe, width=30, show="*")
        self.fb_password_entry.grid(row=2, column=1, sticky="we", pady=4)

        # Кнопка сохранения
        btn_save = ttk.Button(
            frame,
            text="Сохранить настройки",
            style="Accent.TButton",
            command=self.save_settings,
        )
        btn_save.grid(row=5, column=0, columnspan=3, sticky="e", pady=(8, 0))

        frame.grid_columnconfigure(0, weight=1)

        self._load_settings_into_form()

    def _load_settings_into_form(self):
        self.merchant_entry.delete(0, tk.END)
        self.merchant_entry.insert(0, MERCHANT_LOGIN)

        self.password1_entry.delete(0, tk.END)
        self.password1_entry.insert(0, PASSWORD1)

        self.password2_entry.delete(0, tk.END)
        self.password2_entry.insert(0, PASSWORD2)

        self.sno_entry.delete(0, tk.END)
        self.sno_entry.insert(0, SHOP_SNO)

        self.tax_entry.delete(0, tk.END)
        self.tax_entry.insert(0, TAX)

        self.email_entry.delete(0, tk.END)
        self.email_entry.insert(0, CUSTOMER_EMAIL)

        self.is_test_var.set(IS_TEST)

        self.bot_token_entry.delete(0, tk.END)
        self.bot_token_entry.insert(0, BOT_TOKEN)

        self.admin_id_entry.delete(0, tk.END)
        if ADMIN_ID:
            self.admin_id_entry.insert(0, str(ADMIN_ID))

        self.user_chat_id_entry.delete(0, tk.END)
        if USER_CHAT_ID:
            self.user_chat_id_entry.insert(0, str(USER_CHAT_ID))

        self.result_port_entry.delete(0, tk.END)
        self.result_port_entry.insert(0, str(RESULT_PORT))

        self.fb_path_entry.delete(0, tk.END)
        self.fb_path_entry.insert(0, APP_CONFIG.get("fb_db_path", ""))

        self.fb_user_entry.delete(0, tk.END)
        self.fb_user_entry.insert(0, APP_CONFIG.get("fb_user", ""))

        self.fb_password_entry.delete(0, tk.END)
        self.fb_password_entry.insert(0, APP_CONFIG.get("fb_password", ""))

    def save_settings(self):
        cfg = {
            "merchant_login": self.merchant_entry.get().strip(),
            "password1": self.password1_entry.get().strip(),
            "password2": self.password2_entry.get().strip(),
            "shop_sno": self.sno_entry.get().strip() or "patent",
            "tax": self.tax_entry.get().strip() or "none",
            "customer_email": self.email_entry.get().strip() or "example@example.com",
            "is_test": int(self.is_test_var.get() or 0),
            "telegram_token": self.bot_token_entry.get().strip(),
            "admin_id": self.admin_id_entry.get().strip(),
            "user_chat_id": self.user_chat_id_entry.get().strip(),
            "result_port": self.result_port_entry.get().strip(),
            "fb_db_path": self.fb_path_entry.get().strip(),
            "fb_user": self.fb_user_entry.get().strip(),
            "fb_password": self.fb_password_entry.get().strip(),
        }

        save_config(cfg)
        messagebox.showinfo("Настройки", "Настройки сохранены.")

# ---------- Splash и запуск ----------

def show_splash(app_cls):
    splash = tk.Tk()
    splash.title("Запуск BONJOUR")
    splash.overrideredirect(True)

    frame = tk.Frame(splash, bg=COLOR_PRIMARY, padx=24, pady=24)
    frame.pack(fill=tk.BOTH, expand=True)

    lbl = tk.Label(
        frame,
        text="BONJOUR — Robokassa Desktop",
        font=("Segoe UI Semibold", 14),
        fg="#F9FAFB",
        bg=COLOR_PRIMARY,
    )
    lbl.pack()

    sub = tk.Label(
        frame,
        text="Загрузка терминала Robokassa…",
        font=("Segoe UI", 9),
        fg="#E5E7EB",
        bg=COLOR_PRIMARY,
    )
    sub.pack(pady=(10, 0))

    splash.update_idletasks()
    w = splash.winfo_width()
    h = splash.winfo_height()
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    splash.geometry(f"{w}x{h}+{x}+{y}")

    def start_app():
        splash.destroy()
        app = App(APP_CONFIG)
        app.mainloop()

    splash.after(800, start_app)
    splash.mainloop()


