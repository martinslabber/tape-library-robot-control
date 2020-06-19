#!/usr/bin/env python3

# Simulated Tape Library Robot Hardware Abstraction Layer

import math
import asyncio
import io
import random
import collections
import json
import logging

from aiohttp import web

from aiohttp_swagger3 import SwaggerDocs, SwaggerUiSettings

from matplotlib import pyplot as plt

import handlers


class LibraryError(Exception):
    pass


class BaseSlot:

    outline_colour = (0, 0, 0)
    occupied_colour = (0.6, 0.6, 1)
    name_prefix = "x"
    is_drive = False
    is_picker = False

    def __init__(self, column, row):
        self.column = column
        self.row = row
        self.name = self._name()
        self.type = self._type()
        self.tape = None
        self.x = self._x()
        self.y = self._y()

    def __str__(self):
        return self.name

    def _name(self):
        if self.is_picker:
            return "picker"
        else:
            return "{}{:02d}{:02d}".format(self.name_prefix, self.column, self.row)

    def _x(self):
        raise NotImplementedError("_x")

    def _y(self):
        return 16 + self.row * 6

    def _type(self):
        if self.is_drive:
            return "drive"
        elif self.is_picker:
            return "picker"
        else:
            return "slot"

    @property
    def colour(self):
        if self.tape:
            return self.occupied_colour
        else:
            return (1, 1, 1)

    def scan(self):
        return self.tape

    def eject(self):
        if self.tape is None:
            raise LibraryError("{} is empty".format(self.name))
        tape = self.tape
        self.tape = None
        return tape

    def enter(self, tape):
        if self.tape is not None:
            raise LibraryError("{} is not empty".format(self.name))
        self.tape = tape
        return self.tape


class AccessSlot(BaseSlot):

    occupied_colour = (0.5, 1, 0.5)
    name_prefix = "a"

    def _x(self):
        return 4

    def _y(self):
        return 18 + self.row * 3


class Slot(BaseSlot):

    occupied_colour = (0.5, 0.5, 1)
    name_prefix = "s"

    def _x(self):
        return 16 + self.column * 6

    def _y(self):
        return 2 + self.row * 3


class Picker(BaseSlot):

    outline_colour = (1.0, 0.2, 0.2)
    occupied_colour = (1.0, 0.5, 0.5)
    name_prefix = "s"
    is_picker = True

    def _x(self):
        return 10

    def _y(self):
        return 10


class Drive(BaseSlot):

    occupied_colour = (0.5, 0.5, 0.5)
    name_prefix = "d"
    is_drive = True

    def _x(self):
        return 6

    def _y(self):
        return 3 + self.row * 6


class LibraryConfig(dict):
    def load(self):
        pass

    def save(self):
        pass

    def report(self):
        return dict(self)


class LibrarySensors:
    def __init__(self):
        self._sensors = {}
        self.register("door-open", bool, False)
        self.register("temperature-a23", int, 33)
        self.register("temperature-a51", float, 23.2)

    def set(self, name, value):
        self._sensors[name]["value"] = self._sensors[name]["type"](value)

    def get(self, name, value):
        return self._sensors[name]["value"]

    def register(self, name, sensor_type, default):
        self._sensors[name] = {"type": sensor_type, "value": sensor_type(default)}

    def get_all(self):
        out = {}
        for name, sensor in self._sensors.items():
            out[name] = sensor["value"]
        return out

    def report(self):
        return self.get_all()


class Library:
    """A simulated tape library.

    This is only an example and the internal structure of an tape library
    controller will be different.

    There is also alot happening here that is only for the simulation and
    specific to displaying progress.
    """

    def __init__(self):
        self._x = 30
        self._y = 30
        self._x_max = 80
        self._y_max = 50
        self.slots = {}
        self.drives = {}
        self.access_slots = {}
        self.pickers = {}
        self.inventory = {"picker": {}, "drive": {}, "slot": {}}
        self.last_error = None
        self.task = None
        self.tasks = collections.deque()
        self.running = False
        self.setup()
        self.sensors = LibrarySensors()
        self.config = LibraryConfig()

    def setup(self):
        picker = Picker(0, 0)
        self.pickers["p"] = picker
        for dd in range(2):
            drive = Drive(0, dd)
            self.drives[drive.name] = drive
            self.inventory["drive"][drive.name] = None
        self.running = True

        start_tapes = 7
        for sx in range(11):
            for sy in range(16):
                slot = Slot(sx, sy)
                if start_tapes > 0:
                    start_tapes -= 1
                    slot.tape = "tape{}".format(start_tapes)
                self.slots[slot.name] = slot
                # The library dont know what is in it at startup. The simulator
                # knows but we dont expose that.
                self.inventory["slot"][slot.name] = None

    def get_png_buffer(self):
        """Draw the library and return the picture as a buffer."""
        plt.rcParams["figure.figsize"] = (10, 6)
        plt.xlim(0, self._x_max)
        plt.ylim(0, self._y_max)
        for devices in [self.drives, self.access_slots, self.slots, self.pickers]:
            for item in devices.values():
                if item.is_drive:
                    plt.text(
                        item.x,
                        item.y,
                        "      ",
                        size=16,
                        fontfamily="monospace",
                        rotation=0.0,
                        ha="center",
                        va="center",
                        bbox=dict(
                            boxstyle="round", ec=(0, 0, 0), fc=item.occupied_colour
                        ),
                    )
                elif item.is_picker:
                    plt.arrow(item.x, 0, 0, self._y_max)
                    plt.arrow(0, item.y, self._x_max, 0)

                plt.text(
                    item.x,
                    item.y,
                    item.name,
                    size=10,
                    fontfamily="monospace",
                    rotation=0.0,
                    ha="center",
                    va="center",
                    bbox=dict(boxstyle="round", ec=item.outline_colour, fc=item.colour),
                )

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100)
        plt.clf()
        data = buf.getvalue()
        return data

    def move(self):
        """Move the tape library, this increments time.

        This class has no concept of running and the move method steps through the
        actions in the class.
        """
        if self.running and self.pickers:
            if self.task:
                done = getattr(self, "task_" + self.task[0])(self.task[1])
                if done:
                    self.task = None
            else:
                try:
                    self.task = self.tasks.popleft()
                except IndexError:
                    pass

    def random_move(self):
        if self.running and self.pickers:
            picker = self.pickers["p"]
            self._x = picker.x
            self._y = picker.y
            picker.x += random.choice([-1, 0, 1])
            picker.y += random.choice([-1, 0, 1])

            if self._x < 0:
                self._x = 0
            elif self._x > self._x_max:
                self._x = self._x_max

            if self._y < 0:
                self._y = 0
            elif self._y > self._y_max:
                self._y = self._y_max

    def check_queue_max_depth_reached(self):
        """Check that the internal queue has not reached its max."""
        return False

    def info(self):
        """Return an info string."""
        text = "Running={} X={} Y={}".format(self.running, self._x, self._y)
        if self.last_error:
            text += "\n Error: {}".format(self.last_error)
        if self.task:
            text += "\n Task {}({})".format(self.task[0], str(self.task[1]))
        return text

    def task_stop(self, device=None):
        self.running = False
        self.last_error = None
        self.tasks.clear()
        return True

    def task_goto(self, device):
        """Move picker to device"""
        picker = self.pickers["p"]
        delta_x = picker.x - device.x
        delta_y = picker.y - device.y
        done = True

        if delta_x != 0:
            done = False
            self._x = picker.x
            picker.x -= math.copysign(1, delta_x)
            if self._x < 0:
                self._x = 0
            elif self._x > self._x_max:
                self._x = self._x_max

        if delta_y != 0:
            done = False
            self._y = picker.y
            picker.y -= math.copysign(1, delta_y)
            if self._y < 0:
                self._y = 0
            elif self._y > self._y_max:
                self._y = self._y_max

        if done:
            self.task = None
        return done

    def task_scan(self, device):
        tape = device.scan()
        self.last_error = "device {} has tape {}".format(device.name, tape)
        self.inventory["slot"][device.name] = tape
        return True

    def task_eject(self, device):
        """Eject from device into picker."""
        picker = self.pickers["p"]

        try:
            tape = device.eject()
            picker.enter(tape)
            self.inventory[device.type][device.name] = False
            self.inventory[picker.type][picker.name] = True
        except LibraryError as error:
            self.last_error = str(error)
            logging.error("!! " + error)
            self.tasks.clear()
            return False

        return True

    def task_enter(self, device):
        """Eject from picker into device."""
        picker = self.pickers["p"]

        try:
            tape = picker.eject()
            device.enter(tape)
            self.inventory[device.type][device.name] = True
            self.inventory[picker.type][picker.name] = False
        except LibraryError as error:
            self.last_error = str(error)
            logging.error("!! " + error)
            self.tasks.clear()
            return False

        return True

    def standard_action_response(self, name, reply_payload=None, **kwargs):
        out = {"action": name, "params": kwargs}
        if reply_payload is not None:
            out[name] = reply_payload
        return out

    def get_drive_obj(self, drive):
        if not drive:
            error = {
                "error": {
                    "description": "no drive specified",
                    "reason": "notspecified",
                    "type": "drive",
                }
            }
            raise web.HTTPMisdirectedRequest(text=json.dumps(error))
        try:
            drive_class = self.drives[drive]
        except KeyError:
            error = {
                "error": {
                    "description": "no such drive",
                    "drive": drive,
                    "reason": "nosuch",
                    "type": "drive",
                }
            }
            raise web.HTTPMisdirectedRequest(text=json.dumps(error))
        return drive_class

    def get_slot_obj(self, slot):
        if not slot:
            error = {
                "error": {
                    "description": "no slot specified",
                    "reason": "notspecifiec",
                    "type": "slot",
                }
            }
            raise web.HTTPMisdirectedRequest(text=json.dumps(error))
        try:
            slot_class = self.slots[slot]
        except KeyError:
            error = {
                "error": {
                    "description": "no such slot",
                    "slot": slot,
                    "reason": "nosuch",
                    "type": "slot",
                }
            }
            raise web.HTTPMisdirectedRequest(text=json.dumps(error))
        return slot_class

    def action_scan(self, slot):
        slot_class = self.get_slot_obj(slot)
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("scan", slot_class))
        return self.standard_action_response("scan", slot=slot)

    def action_inventory(self):
        return self.standard_action_response("inventory", reply_payload=self.inventory)

    def action_load(self, slot, drive):
        slot_class = self.get_slot_obj(slot)
        drive_class = self.get_drive_obj(drive)
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("eject", slot_class))
        self.tasks.append(("goto", drive_class))
        self.tasks.append(("enter", drive_class))
        return self.standard_action_response("load", slot=slot, drive=drive)

    def action_unload(self, slot, drive):
        slot_class = self.get_slot_obj(slot)
        drive_class = self.get_drive_obj(drive)
        self.tasks.append(("goto", drive_class))
        self.tasks.append(("eject", drive_class))
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("enter", slot_class))
        return self.standard_action_response("unload", slot=slot, drive=drive)

    def action_transfer(self, source, target):
        def slot_or_access(s):
            if s in self.slots:
                return self.slots[s]
            else:
                return self.access_slots[s]

        slot_class = self.get_slot_obj(source)
        target_class = self.get_slot_obj(target)
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("eject", slot_class))
        self.tasks.append(("goto", target_class))
        self.tasks.append(("enter", target_class))
        return self.standard_action_response("transfer", source=source, target=target)

    def action_sensors(self):
        reply = self.sensors.report()
        return self.standard_action_response("sensors", reply_payload=reply)

    def action_state(self):
        reply = {"locked": not self.running, "busy": bool(self.tasks)}
        return self.standard_action_response("state", reply_payload=reply)

    def action_config(self, **kwargs):
        self.config.update(kwargs)
        reply = self.config.report()
        return self.standard_action_response("config", reply_payload=reply, **kwargs)

    def action_lock(self):
        self.task_stop()
        return self.standard_action_response("lock")

    def action_unlock(self):
        self.running = True
        return self.standard_action_response("unlock")

    def action_park(self):
        self.task = None
        self.tasks.clear()
        self.tasks.append(("goto", self.slots["s0000"]))
        self.tasks.append(("stop", self.pickers["p"]))
        return self.standard_action_response("park")


async def map_img(request):
    # request.app["tape_library"].move()
    buf = request.app["tape_library"].get_png_buffer()
    return web.Response(body=buf, content_type="image/png")


async def map_page(request):
    text = """<html>
    <head>
    <style>
    .flex-container {
        display: flex;
    }
    .flex-child {
        flex: 1;
        border: 1px solid blue;
    }
    .flex-child:first-child {
        margin-right: 20px;
    }
    </style>
    <script type="text/JavaScript">
    var url = "/show.png"; //url to load image from
    var refreshInterval = 1000; //in ms
    var drawDate = true; //draw date string
    var img;

    function init() {
        var canvas = document.getElementById("canvas");
        var context = canvas.getContext("2d");
        img = new Image();
        img.onload = function() {
            canvas.setAttribute("width", img.width)
            canvas.setAttribute("height", img.height)
            context.drawImage(this, 0, 0);
            if(drawDate) {
                var now = new Date();
                var maxWidth = 100;
                var x = img.width-10-maxWidth;
                var y = img.height-10;
            }
        };
        refresh();
    }
    function updatetxt() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/log');
    xhr.onload = function() {
    if (xhr.status === 200) {
        document.getElementById('logTextarea').value = xhr.responseText;
    }
    else {
        document.getElementById('logTextarea').value = xhr.status;
    }
    };
    xhr.send();

    }
    function refresh()
    {
        img.src = url + "?t=" + new Date().getTime();
        setTimeout("refresh()",refreshInterval);
        updatetxt();
    }
    </script>
    <title>JavaScript Refresh Example</title>
    </head>
    <body onload="JavaScript:init();">
    <div class="flex-container">
    <div class="flex-child magenta">
    Monitoring
    <div>
      <canvas id="canvas"/>
      </div>
      <div>
      <textarea id="logTextarea" name="something" rows="8" cols="100">
      This text gets removed</textarea>
      </div>
      </div>
      <div class="flex-child green">
        Control
        <div>
          <iframe name="hiddenFrame"></iframe>
        </div>
        Actions:
        <div>
          <form action="/load" target="hiddenFrame">
            <input type="submit" value="load">
            <label for="slot">from slot</label>
            <input type="text" id="slot" name="slot" value="">
            <label for="drive">to drive</label>
            <input type="text" id="drive" name="drive" value=""><br><br>
          </form>
        </div>
        <div>
          <form action="/unload" target="hiddenFrame">
            <input type="submit" value="unload">
            <label for="slot">to slot</label>
            <input type="text" id="slot" name="slot" value="">
            <label for="drive">from drive</label>
            <input type="text" id="drive" name="drive" value=""><br><br>
          </form>
        </div>
        <div>
          <form action="/transfer" target="hiddenFrame">
            <input type="submit" value="transfer">
            <label for="slot">from slot</label>
            <input type="text" id="slot" name="slot" value="">
            <label for="slot">to slot</label>
            <input type="text" id="targetslot" name="targetslot" value=""><br><br>
          </form>
        </div>
        <div>
          <form action="/scan" target="hiddenFrame">
            <input type="submit" value="scan">
            <label for="slot">slot</label>
            <input type="text" id="slot" name="slot" value="">
          </form>
        </div>
        <div>
          <form action="/lock" target="hiddenFrame">
            <input type="submit" value="lock">
          </form>
          <form action="/unlock" target="hiddenFrame">
            <input type="submit" value="unlock">
          </form>
          <form action="/park" target="hiddenFrame">
            <input type="submit" value="park">
          </form>
        </div>
      </div>
    </div>
    <a href=/api/doc>Swagger API doc</a>
    </body>
    </html>"""
    return web.Response(text=text.strip(), content_type="text/html")


async def sim_runner(app):
    # your infinite loop here, for example:
    while True:
        app["tape_library"].move()
        await asyncio.sleep(1)


async def map_page1(request):
    """
    ---
    description: This end-point allow to test that service is up.
    tags:
    - Health check
    produces:
    - text/plain
    responses:
        "200":
            description: successful operation. Return "pong" text
        "405":
            description: invalid HTTP Method
    """

    request.app["tape_library"].move()
    text = """<html><head>
    <title>HTML in 10 Simple Steps or Less</title>
    <meta http-equiv="refresh" content="1"> <!-- See the difference? -->
    </head>
    <body>
    <img src=/show.png>"""
    text += request.app["tape_library"].info()
    text += """</body></html>"""
    return web.Response(text=text.strip(), content_type="text/html")


async def log_page(request):
    text = request.app["tape_library"].info()
    return web.Response(text=text.strip(), content_type="text/html")


async def handle(request):
    name = request.match_info.get("name", "Anonymous")
    text = "{} called with\n{}\n".format(name, dict(request.query))
    library = request.app["tape_library"]
    if hasattr(library, "action_" + name):
        text += str(getattr(library, "action_" + name)(**request.query))
    return web.Response(text=text)


async def start_background_tasks(app):
    app["sim_runner"] = asyncio.Task(sim_runner(app))


app = web.Application()
app["tape_library"] = Library()
app.on_startup.append(start_background_tasks)
app.add_routes(
    [
        web.get("/", map_page),
        web.get("/show.png", map_img),
        web.get("/log", log_page),
        web.get("/{name}", handle),  # A lazy catch all while working on web UI hack
    ]
)

if __name__ == "__main__":
    swagger = SwaggerDocs(
        app,
        swagger_ui_settings=SwaggerUiSettings(path="/api/doc"),
        title="Tape Library Robot API",
        version="1.0.0",
        components="swagger.yaml",
    )
    swagger.add_routes(
        [
            web.get("/load", handlers.load_handle),
            web.get("/unload", handlers.unload_handle),
            web.get("/transfer", handlers.transfer_handle),
            web.get("/inventory", handlers.inventory_handle),
            web.get("/scan", handlers.scan_handle),
            web.get("/sensors", handlers.sensors_handle),
            web.get("/config", handlers.config_handle),
            web.get("/state", handlers.state_handle),
            web.get("/park", handlers.park_handle),
            web.get("/lock", handlers.lock_handle),
            web.get("/unlock", handlers.unlock_handle),
        ]
    )
    web.run_app(app)
