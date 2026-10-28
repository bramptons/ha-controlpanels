import json
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any
import paho.mqtt.client as mqtt
import websocket

PULSE_CYCLES = 3

DEFAULT_MQTT_CONFIG: dict[str, Any] = {
    "broker": "localhost",
    "port": 1883,
    "keepalive": 60,
}

SWITCH_CONFIG_PATH = Path(__file__).with_name("switch_sets.json")
APP_CONFIG_PATH = Path(__file__).with_name("config.json")


DEFAULT_SWITCH_SETS: list[dict[str, str]] = []
DEFAULT_SENSOR_ITEMS: list[dict[str, str]] = []
DEFAULT_HOME_ASSISTANT_CONFIG: dict[str, Any] = {
    "poll_interval_seconds": 10,
}
DEFAULT_ICONS: dict[str, str] = {
    "switch_light": "💡",
    "switch_power": "⚡",
    "sensor_door": "🚪",
    "sensor_window": "🪟",
}

SENSOR_STATUS_STYLES = {
    "open": {"bg": "#c62828", "fg": "white", "status": "OPEN"},
    "closed": {"bg": "#2e7d32", "fg": "white", "status": "CLOSED"},
    "unknown": {"bg": "#616161", "fg": "white", "status": "UNKNOWN"},
}

APP_BG_COLOR = "#1e1035"
APP_FG_COLOR = "white"

OPEN_STATES = {"on", "open", "opening"}
CLOSED_STATES = {"off", "closed", "closing"}
TARGET_WINDOW_WIDTH = 1024
TARGET_WINDOW_HEIGHT = 600
SWITCH_GRID_COLUMNS = 6
SWITCH_GRID_ROWS = 3
MIN_SENSOR_TILE_WIDTH = 160
MIN_SWITCH_BUTTON_FONT_SIZE = 11
MAX_SWITCH_BUTTON_FONT_SIZE = 16
MIN_SWITCH_LABEL_FONT_SIZE = 10
MAX_SWITCH_LABEL_FONT_SIZE = 13
MIN_SWITCH_STATE_FONT_SIZE = 9
MAX_SWITCH_STATE_FONT_SIZE = 11
DEBUG_LOGGING = True

SWITCH_BUTTON_STYLES = {
    "on": {
        "text": "ON",
        "bg": "#2e7d32",
        "activebackground": "#43a047",
    },
    "off": {
        "text": "OFF",
        "bg": "#b71c1c",
        "activebackground": "#c62828",
    },
    "unknown": {
        "text": "UNKNOWN",
        "bg": "#424242",
        "activebackground": "#616161",
    },
}


def parse_switch_sets(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []

    loaded: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        label = item.get("label")
        switch_type = item.get("type")
        command_topic = item.get("command_topic")
        state_topic = item.get("state_topic")

        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(switch_type, str) or switch_type not in {"light", "power"}:
            continue
        if not isinstance(command_topic, str) or not command_topic.strip():
            continue
        if not isinstance(state_topic, str) or not state_topic.strip():
            continue

        parsed_item = {
                "label": label.strip(),
                "type": switch_type,
                "command_topic": command_topic.strip(),
                "state_topic": state_topic.strip(),
            }
        entity_id = item.get("entity_id")
        if isinstance(entity_id, str) and entity_id.strip():
            parsed_item["entity_id"] = entity_id.strip()
        loaded.append(parsed_item)

    return loaded


def normalize_sensor_kind(value: str) -> str:
    value_lower = value.strip().lower()
    if "door" in value_lower:
        return "door"
    if "window" in value_lower:
        return "window"
    return ""


def parse_sensor_items(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []

    loaded: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        label = item.get("label")
        entity_id = item.get("entity_id")
        sensor_kind = item.get("kind", "")

        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(entity_id, str) or not entity_id.strip():
            continue

        kind = ""
        if isinstance(sensor_kind, str):
            kind = normalize_sensor_kind(sensor_kind)
        if not kind:
            kind = normalize_sensor_kind(entity_id)
        if not kind:
            continue

        loaded.append(
            {
                "label": label.strip(),
                "entity_id": entity_id.strip(),
                "kind": kind,
            }
        )

    # Keep a single row of six indicators as requested.
    return loaded[:6]


def load_json_config(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except Exception:
        return None


def load_panel_config() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any], dict[str, str], dict[str, Any]]:
    switch_sets = DEFAULT_SWITCH_SETS
    switch_data = load_json_config(SWITCH_CONFIG_PATH)
    if isinstance(switch_data, list):
        switch_sets = parse_switch_sets(switch_data)
    elif isinstance(switch_data, dict):
        switch_sets = parse_switch_sets(switch_data.get("switches", []))

    data = load_json_config(APP_CONFIG_PATH)
    if not isinstance(data, dict):
        return switch_sets, DEFAULT_SENSOR_ITEMS, DEFAULT_HOME_ASSISTANT_CONFIG.copy(), DEFAULT_ICONS.copy(), DEFAULT_MQTT_CONFIG.copy()

    sensor_items = parse_sensor_items(data.get("sensors", []))

    home_assistant = DEFAULT_HOME_ASSISTANT_CONFIG.copy()
    raw_home_assistant = data.get("home_assistant", {})
    if isinstance(raw_home_assistant, dict):
        if isinstance(raw_home_assistant.get("url"), str) and raw_home_assistant["url"].strip():
            home_assistant["url"] = raw_home_assistant["url"].strip()
        if isinstance(raw_home_assistant.get("access_token"), str):
            home_assistant["access_token"] = raw_home_assistant["access_token"].strip()
        if isinstance(raw_home_assistant.get("poll_interval_seconds"), int) and raw_home_assistant["poll_interval_seconds"] >= 5:
            home_assistant["poll_interval_seconds"] = raw_home_assistant["poll_interval_seconds"]

    icons = DEFAULT_ICONS.copy()
    raw_icons = data.get("icons", {})
    if isinstance(raw_icons, dict):
        for key in ["switch_light", "switch_power", "sensor_door", "sensor_window"]:
            if isinstance(raw_icons.get(key), str) and raw_icons[key].strip():
                icons[key] = raw_icons[key].strip()

    mqtt_config = DEFAULT_MQTT_CONFIG.copy()
    raw_mqtt = data.get("mqtt", {})
    if isinstance(raw_mqtt, dict):
        if isinstance(raw_mqtt.get("broker"), str) and raw_mqtt["broker"].strip():
            mqtt_config["broker"] = raw_mqtt["broker"].strip()
        if isinstance(raw_mqtt.get("port"), int) and raw_mqtt["port"] > 0:
            mqtt_config["port"] = raw_mqtt["port"]
        if isinstance(raw_mqtt.get("keepalive"), int) and raw_mqtt["keepalive"] > 0:
            mqtt_config["keepalive"] = raw_mqtt["keepalive"]

    return switch_sets, sensor_items, home_assistant, icons, mqtt_config


def get_switch_icon(switch_type: str, icons: dict[str, str]) -> str:
    if switch_type == "power":
        return icons.get("switch_power", "⚡")
    return icons.get("switch_light", "💡")


def get_sensor_icon(sensor_kind: str, icons: dict[str, str]) -> str:
    if sensor_kind == "door":
        return icons.get("sensor_door", "🚪")
    return icons.get("sensor_window", "🪟")


def classify_sensor_state(raw_state: str) -> str:
    state = raw_state.strip().lower()
    if state in OPEN_STATES:
        return "open"
    if state in CLOSED_STATES:
        return "closed"
    return "unknown"


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


class SwitchPanelApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Violet Control Panel")
        self.switch_sets, self.sensor_items, self.home_assistant_config, self.icons, self.mqtt_config = load_panel_config()
        self.root.minsize(TARGET_WINDOW_WIDTH, TARGET_WINDOW_HEIGHT)
        self.root.maxsize(TARGET_WINDOW_WIDTH, TARGET_WINDOW_HEIGHT)
        self.root.configure(bg=APP_BG_COLOR)
        self.ha_stop_event = threading.Event()
        self.ha_refresh_event = threading.Event()
        self.ha_polling_enabled = False
        self.sensor_ui: dict[str, dict[str, Any]] = {}
        self.layout_refresh_job: str | None = None

        self.root.grid_rowconfigure(1, weight=3)
        self.root.grid_rowconfigure(2, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.state_topic_map = {
            config["state_topic"]: index for index, config in enumerate(self.switch_sets)
        }
        self.switch_ui: list[dict] = []

        self.header_label = tk.Label(root, text="Violet Control Panel", font=("Segoe UI", 14, "bold"), pady=10, bg=APP_BG_COLOR, fg=APP_FG_COLOR)
        self.header_label.grid(row=0, column=0, sticky="ew")

        self.frame = tk.Frame(root, bg=APP_BG_COLOR)
        self.frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=10)
        self.switch_frames: list[tk.Frame] = []

        for index, config in enumerate(self.switch_sets):
            switch_icon = get_switch_icon(config["type"], self.icons)
            set_frame = tk.Frame(self.frame, bg=APP_BG_COLOR)

            set_frame.grid_columnconfigure(0, weight=1)
            set_frame.grid_rowconfigure(1, weight=1)

            switch_label = tk.Label(set_frame, text=f"{switch_icon} {config['label']}", font=("Segoe UI", 11, "bold"), bg=APP_BG_COLOR, fg=APP_FG_COLOR)
            switch_label.grid(row=0, column=0, pady=(0, 8))

            toggle_button = tk.Button(
                set_frame,
                text="UNKNOWN",
                font=("Segoe UI", 12, "bold"),
                bg=SWITCH_BUTTON_STYLES["unknown"]["bg"],
                fg="white",
                activebackground=SWITCH_BUTTON_STYLES["unknown"]["activebackground"],
                command=lambda idx=index: self.toggle_switch(idx),
            )
            toggle_button.grid(row=1, column=0, pady=(0, 8), sticky="nsew")

            state_label = tk.Label(set_frame, text="State: UNKNOWN", font=("Segoe UI", 10, "bold"), bg=APP_BG_COLOR, fg=APP_FG_COLOR)
            state_label.grid(row=2, column=0)

            self.switch_ui.append(
                {
                    "current_state": "unknown",
                    "switch_label": switch_label,
                    "toggle_button": toggle_button,
                    "state_label": state_label,
                    "command_topic": config["command_topic"],
                }
            )
            self.switch_frames.append(set_frame)

        self.indicator_frame = tk.Frame(root, bg=APP_BG_COLOR)
        self.indicator_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 6))

        self.sensor_widgets: list[tk.Widget] = []

        for index, sensor in enumerate(self.sensor_items):
            sensor_icon = get_sensor_icon(sensor["kind"], self.icons)
            sensor_label = tk.Label(
                self.indicator_frame,
                text=f"{sensor_icon} {sensor['label']}\nUNKNOWN",
                font=("Segoe UI", 10, "bold"),
                bg=SENSOR_STATUS_STYLES["unknown"]["bg"],
                fg=SENSOR_STATUS_STYLES["unknown"]["fg"],
                padx=10,
                pady=10,
                width=14,
                height=3,
                wraplength=140,
                anchor="center",
                relief="ridge",
                bd=2,
                justify="center",
            )

            self.sensor_ui[sensor["entity_id"]] = {
                "label": sensor["label"],
                "kind": sensor["kind"],
                "widget": sensor_label,
            }
            self.sensor_widgets.append(sensor_label)

        self.info_label = tk.Label(
            root,
            text=f"Broker: {self.mqtt_config['broker']}",
            font=("Segoe UI", 9),
            bg=APP_BG_COLOR,
            fg=APP_FG_COLOR,
        )
        self.info_label.grid(row=3, column=0, sticky="ew", pady=(8, 10), padx=16)

        self.ws_status_label = tk.Label(
            root,
            text="Home Assistant WS: DISCONNECTED",
            font=("Segoe UI", 9),
            bg=APP_BG_COLOR,
            fg=APP_FG_COLOR,
            cursor="hand2",
        )
        self.ws_status_label.grid(row=4, column=0, sticky="ew", pady=(0, 10), padx=16)
        self.ws_status_label.bind("<Button-1>", self.refresh_home_assistant_states)

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.reset_all_switches_to_unknown()
        self.maximize_window()
        self.root.bind("<Configure>", self.on_root_configure)
        self.root.after(0, self.refresh_layout)
        self.root.after(200, self.refresh_layout)
        self.root.after(600, self.refresh_layout)
        self.connect_mqtt()
        self.start_home_assistant_sensor_updates()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, message: str):
        if not DEBUG_LOGGING:
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

    def __getattr__(self, name: str):
        normalized_name = name.replace(" ", "_").lower()
        if normalized_name in {"maximize_window", "maximise_window", "maximizewindow"}:
            return self.maximize_window
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def maximize_window(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(TARGET_WINDOW_WIDTH, screen_width)
        height = min(TARGET_WINDOW_HEIGHT, screen_height)
        x_offset = max((screen_width - width) // 2, 0)
        y_offset = max((screen_height - height) // 2, 0)
        self.root.geometry(f"{width}x{height}+{x_offset}+{y_offset}")

    def on_root_configure(self, event):
        if event.widget is not self.root:
            return

        if self.layout_refresh_job is not None:
            self.root.after_cancel(self.layout_refresh_job)
        self.layout_refresh_job = self.root.after(100, self.refresh_layout)

    def refresh_layout(self):
        self.layout_refresh_job = None
        self.arrange_switch_grid()
        self.arrange_tiles(self.indicator_frame, self.sensor_widgets, MIN_SENSOR_TILE_WIDTH, 6, "sensors", None, SWITCH_GRID_COLUMNS)
        self.update_switch_scaling()

    def arrange_switch_grid(self):
        for column in range(len(self.switch_frames)):
            self.frame.grid_columnconfigure(column, weight=0)
        for row in range(len(self.switch_frames)):
            self.frame.grid_rowconfigure(row, weight=0)

        for column in range(SWITCH_GRID_COLUMNS):
            self.frame.grid_columnconfigure(column, weight=1, uniform="switches")
        for row in range(SWITCH_GRID_ROWS):
            self.frame.grid_rowconfigure(row, weight=1)

        for index, widget in enumerate(self.switch_frames):
            if index >= SWITCH_GRID_COLUMNS * SWITCH_GRID_ROWS:
                widget.grid_forget()
                continue
            row = index // SWITCH_GRID_COLUMNS
            column = index % SWITCH_GRID_COLUMNS
            widget.grid(row=row, column=column, padx=6, pady=6, sticky="nsew")

    def update_switch_scaling(self):
        switch_count = len(self.switch_frames)
        if switch_count == 0:
            return

        available_width = max(self.frame.winfo_width(), TARGET_WINDOW_WIDTH - 32)
        columns = SWITCH_GRID_COLUMNS
        total_horizontal_padding = columns * 12
        tile_width = max((available_width - total_horizontal_padding) // columns, 80)

        button_font_size = clamp(tile_width // 15, MIN_SWITCH_BUTTON_FONT_SIZE, MAX_SWITCH_BUTTON_FONT_SIZE)
        label_font_size = clamp(tile_width // 18, MIN_SWITCH_LABEL_FONT_SIZE, MAX_SWITCH_LABEL_FONT_SIZE)
        state_font_size = clamp(tile_width // 22, MIN_SWITCH_STATE_FONT_SIZE, MAX_SWITCH_STATE_FONT_SIZE)

        for ui in self.switch_ui:
            ui["switch_label"].config(font=("Segoe UI", label_font_size, "bold"), wraplength=max(tile_width - 24, 120))
            ui["toggle_button"].config(font=("Segoe UI", button_font_size, "bold"))
            ui["state_label"].config(font=("Segoe UI", state_font_size, "bold"), wraplength=max(tile_width - 24, 120))

    def arrange_tiles(
        self,
        container: tk.Widget,
        widgets: list[tk.Widget],
        min_tile_width: int,
        horizontal_padding: int,
        uniform_name: str,
        available_width: int | None = None,
        max_columns: int | None = None,
    ):
        if not widgets:
            return

        if available_width is None:
            available_width = max(self.root.winfo_width() - 32, 320)

        columns = max(1, available_width // min_tile_width)
        columns = min(columns, len(widgets))
        if max_columns is not None:
            columns = min(columns, max_columns)
        rows = (len(widgets) + columns - 1) // columns

        for column in range(len(widgets)):
            container.grid_columnconfigure(column, weight=0, uniform=uniform_name)
        for row in range(len(widgets)):
            container.grid_rowconfigure(row, weight=0)

        for column in range(columns):
            container.grid_columnconfigure(column, weight=1, uniform=uniform_name)
        for row in range(rows):
            container.grid_rowconfigure(row, weight=1)

        for index, widget in enumerate(widgets):
            row = index // columns
            column = index % columns
            widget.grid(row=row, column=column, padx=horizontal_padding, pady=6, sticky="nsew")

    def connect_mqtt(self):
        broker = self.mqtt_config["broker"]
        port = self.mqtt_config["port"]
        keepalive = self.mqtt_config["keepalive"]
        try:
            self.log(f"MQTT: connecting to {broker}:{port}")
            self.client.connect(broker, port, keepalive)
            self.client.loop_start()
            self.log("MQTT: loop started")
        except Exception as exc:
            self.log(f"MQTT: connect failed ({type(exc).__name__}): {exc}")
            messagebox.showerror("MQTT Connection Error", str(exc))

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.log(f"MQTT: connected (reason_code={reason_code})")
            for config in self.switch_sets:
                client.subscribe(config["state_topic"])
                self.log(f"MQTT: subscribed to {config['state_topic']}")
            listening = ", ".join(config["state_topic"] for config in self.switch_sets)
            broker = self.mqtt_config["broker"]
            self.root.after(0, lambda: self.info_label.config(text=f"Connected to {broker} | Listening: {listening}"))
        else:
            self.log(f"MQTT: connect rejected (reason_code={reason_code})")
            self.root.after(0, lambda: self.info_label.config(text=f"MQTT connect failed: {reason_code}"))

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.log(f"MQTT: disconnected (reason_code={reason_code}, flags={disconnect_flags})")
        self.root.after(0, lambda: self.info_label.config(text=f"Disconnected from broker ({reason_code})"))

    def on_message(self, client, userdata, message):
        payload = message.payload.decode("utf-8", errors="ignore").strip().lower()
        if payload not in {"on", "off"}:
            self.log(f"MQTT: ignored unsupported payload on {message.topic}: {payload!r}")
            return
        topic = message.topic
        switch_index = self.state_topic_map.get(topic)
        if switch_index is None:
            self.log(f"MQTT: no switch mapping for topic {topic}")
            return
        self.log(f"MQTT: state update {topic} -> {payload}")
        self.root.after(0, lambda: self.apply_state(switch_index, payload))

    def send_command(self, command_topic: str, command: str):
        try:
            self.client.publish(command_topic, command, qos=1, retain=False)
            self.log(f"MQTT: published {command!r} to {command_topic}")
            self.info_label.config(text=f"Command sent: {command.upper()} -> {command_topic}")
        except Exception as exc:
            self.log(f"MQTT: publish failed ({type(exc).__name__}): {exc}")
            messagebox.showerror("Publish Error", str(exc))

    def toggle_switch(self, switch_index: int):
        ui = self.switch_ui[switch_index]
        current_state = ui["current_state"]
        if current_state == "on":
            next_command = "off"
        elif current_state == "off":
            next_command = "on"
        else:
            next_command = "toggle"
        self.send_command(ui["command_topic"], next_command)

    def apply_switch_button_style(self, switch_index: int, state: str):
        ui = self.switch_ui[switch_index]
        style = SWITCH_BUTTON_STYLES.get(state, SWITCH_BUTTON_STYLES["unknown"])
        ui["toggle_button"].config(
            text=style["text"],
            bg=style["bg"],
            activebackground=style["activebackground"],
            relief="sunken" if state in {"on", "off"} else "raised",
        )

    def apply_state(self, switch_index: int, state: str):
        ui = self.switch_ui[switch_index]
        ui["current_state"] = state
        ui["state_label"].config(text=f"State: {state.upper()}")
        self.apply_switch_button_style(switch_index, state)

    def start_home_assistant_sensor_updates(self):
        if not self.sensor_items and not self.switch_sets:
            self.log("WS: state polling disabled (no devices or sensors configured)")
            self.ws_status_label.config(text="Home Assistant WS: NOTHING CONFIGURED")
            return

        url = self.home_assistant_config.get("url", "")
        access_token = self.home_assistant_config.get("access_token", "")
        if not isinstance(url, str) or not url.strip():
            self.log("WS: URL missing in switch_sets.json")
            self.info_label.config(text="Home Assistant URL missing in switch_sets.json")
            self.ws_status_label.config(text="Home Assistant WS: URL MISSING")
            return
        if not isinstance(access_token, str) or not access_token.strip():
            self.log("WS: access_token missing in switch_sets.json")
            self.info_label.config(text="Home Assistant token missing in switch_sets.json")
            self.ws_status_label.config(text="Home Assistant WS: TOKEN MISSING")
            return

        self.ws_status_label.config(text="Home Assistant WS: CONNECTING")
        self.ha_polling_enabled = True
        state_thread = threading.Thread(target=self.poll_home_assistant_states_loop, daemon=True)
        state_thread.start()

    def refresh_home_assistant_states(self, _event=None):
        """Wake the polling thread for an immediate device and sensor refresh."""
        if self.ha_stop_event.is_set():
            return
        self.log("Status: manual MQTT and Home Assistant refresh requested")
        self.refresh_mqtt_switch_states()
        if self.ha_polling_enabled:
            self.ws_status_label.config(text="Home Assistant WS: REFRESHING DEVICES + SENSORS...")
            self.ha_refresh_event.set()

    def refresh_mqtt_switch_states(self):
        """Re-subscribe so the broker sends each retained switch state again."""
        if not self.client.is_connected():
            self.log("MQTT: state refresh skipped because broker is disconnected")
            return
        for config in self.switch_sets:
            topic = config["state_topic"]
            self.client.unsubscribe(topic)
            self.client.subscribe(topic)
            self.log(f"MQTT: requested retained state for {topic}")

    def poll_home_assistant_states_loop(self):
        poll_interval = int(self.home_assistant_config.get("poll_interval_seconds", 10))
        poll_interval = max(5, poll_interval)

        while not self.ha_stop_event.is_set():
            states, status = self.get_device_states_from_home_assistant()
            self.log(f"WS: poll result status={status}, states={len(states)}")
            self.root.after(0, lambda value=status: self.ws_status_label.config(text=self.format_ws_status(value)))
            if states:
                self.root.after(0, lambda new_states=states: self.apply_home_assistant_states(new_states))
            self.ha_refresh_event.wait(poll_interval)
            self.ha_refresh_event.clear()

    def format_ws_status(self, status: str) -> str:
        max_length = 120
        if len(status) > max_length:
            status = status[: max_length - 3] + "..."
        return f"Home Assistant WS: {status}"

    def get_device_states_from_home_assistant(self) -> tuple[dict[str, str], str]:
        url = self.home_assistant_config.get("url", "")
        access_token = self.home_assistant_config.get("access_token", "")

        if not isinstance(url, str) or not url.strip():
            return {}, "URL MISSING"
        if not isinstance(access_token, str) or not access_token.strip():
            return {}, "TOKEN MISSING"

        requested_entities = set(self.sensor_ui.keys())
        requested_entities.update(
            config["entity_id"] for config in self.switch_sets if config.get("entity_id")
        )

        try:
            self.log(f"WS: opening connection to {url}")
            ws = websocket.create_connection(url, timeout=8)
            self.log("WS: socket connected")

            hello_message = json.loads(ws.recv())
            if hello_message.get("type") != "auth_required":
                self.log(f"WS: unexpected hello payload: {hello_message}")
                ws.close()
                return {}, f"AUTH HANDSHAKE FAILED ({hello_message.get('type', 'unknown')})"

            ws.send(json.dumps({"type": "auth", "access_token": access_token}))
            auth_response = json.loads(ws.recv())
            if auth_response.get("type") != "auth_ok":
                self.log(f"WS: auth failed response: {auth_response}")
                ws.close()
                message = auth_response.get("message", "auth failed")
                return {}, f"AUTH FAILED ({message})"
            self.log("WS: auth successful")

            ws.send(json.dumps({"id": 1, "type": "get_states"}))
            while True:
                response = json.loads(ws.recv())
                if response.get("id") != 1:
                    continue
                if response.get("type") != "result" or not response.get("success"):
                    ws.close()
                    query_error = response.get("error", {}) if isinstance(response.get("error"), dict) else {}
                    query_message = query_error.get("message", "unknown query error")
                    return {}, f"QUERY FAILED ({query_message})"

                states: dict[str, str] = {}
                for item in response.get("result", []):
                    if not isinstance(item, dict):
                        continue
                    entity_id = item.get("entity_id")
                    state = item.get("state")
                    if not isinstance(entity_id, str) or not isinstance(state, str):
                        continue
                    if entity_id in requested_entities:
                        states[entity_id] = state

                ws.close()
                return states, "CONNECTED"
        except Exception as exc:
            self.log(f"WS: connection/query error ({type(exc).__name__}): {exc}")
            return {}, f"DISCONNECTED ({type(exc).__name__}: {exc})"

    def apply_sensor_states(self, states: dict[str, str]):
        for entity_id, ui in self.sensor_ui.items():
            raw_state = states.get(entity_id, "unknown")
            status_key = classify_sensor_state(raw_state)
            style = SENSOR_STATUS_STYLES[status_key]
            icon = get_sensor_icon(ui["kind"], self.icons)

            ui["widget"].config(
                text=f"{icon} {ui['label']}\n{style['status']}",
                bg=style["bg"],
                fg=style["fg"],
            )

    def apply_home_assistant_states(self, states: dict[str, str]):
        self.apply_sensor_states(states)

        for index, config in enumerate(self.switch_sets):
            entity_id = config.get("entity_id")
            if not entity_id:
                # MQTT is authoritative when no HA entity is explicitly configured.
                continue

            state = states.get(entity_id, "").strip().lower()
            if state in {"on", "off"}:
                self.apply_state(index, state)
            else:
                self.log(f"WS: no usable state for {config['label']} ({entity_id})")

    def reset_all_switches_to_unknown(self):
        """Reset all switches to unknown state on startup."""
        for index, ui in enumerate(self.switch_ui):
            ui["current_state"] = "unknown"
            ui["state_label"].config(text="State: UNKNOWN")
            self.apply_switch_button_style(index, "unknown")

    def on_close(self):
        self.ha_stop_event.set()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        finally:
            self.root.destroy()


def main():
    root = tk.Tk()
    root.bind("<Escape>", lambda e: root.destroy())
    SwitchPanelApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
