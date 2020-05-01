#!/usr/bin/env python3

# Simulated Tape Library Robot Hardware Abstraction Layer

import math
import asyncio
from aiohttp import web
import io
import random
from matplotlib import pyplot as plt
import collections


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


class Library:
    def __init__(self):
        self._x = 30
        self._y = 30
        self._x_max = 80
        self._y_max = 50
        self.slots = {}
        self.drives = {}
        self.access_slots = {}
        self.pickers = {}
        self.setup()
        self.running = True
        self.task = None
        self.tasks = collections.deque()
        self.last_error = None

    def setup(self):
        picker = Picker(0, 0)
        self.pickers["p"] = picker
        for ee in range(6):
            accessslot = AccessSlot(0, ee)
            self.access_slots[accessslot.name] = accessslot
        for dd in range(2):
            drive = Drive(0, dd)
            self.drives[drive.name] = drive

        start_tapes = 7
        for sx in range(11):
            for sy in range(16):
                slot = Slot(sx, sy)
                if start_tapes > 0:
                    start_tapes -= 1
                    slot.tape = "tape{}".format(start_tapes)
                self.slots[slot.name] = slot

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
        return True

    def task_eject(self, device):
        """Eject from device into picker."""
        picker = self.pickers["p"]

        try:
            tape = device.eject()
            picker.enter(tape)
        except LibraryError as error:
            self.last_error = str(error)
            print("!! " + error)
            self.tasks.clear()
            return False

        return True

    def task_enter(self, device):
        """Eject from picker into device."""
        picker = self.pickers["p"]

        try:
            tape = picker.eject()
            device.enter(tape)
        except LibraryError as error:
            self.last_error = str(error)
            print("!! " + error)
            self.tasks.clear()
            return False

        return True

    def action_scan(self, slot):
        slot_class = self.slots[slot]
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("scan", slot_class))

    def action_load(self, slot, drive):
        slot_class = self.slots[slot]
        drive_class = self.drives[drive]
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("eject", slot_class))
        self.tasks.append(("goto", drive_class))
        self.tasks.append(("enter", drive_class))
        return "Loading from {} to {}".format(slot, drive)

    def action_unload(self, slot, drive):
        slot_class = self.slots[slot]
        drive_class = self.drives[drive]
        self.tasks.append(("goto", drive_class))
        self.tasks.append(("eject", drive_class))
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("enter", slot_class))
        return "Loading from {} to {}".format(slot, drive)

    def action_transfer(self, slot, targetslot):
        def slot_or_access(s):
            if s in self.slots:
                return self.slots[s]
            else:
                return self.access_slots[s]

        slot_class = slot_or_access(slot)
        target_class = slot_or_access(targetslot)
        self.tasks.append(("goto", slot_class))
        self.tasks.append(("eject", slot_class))
        self.tasks.append(("goto", target_class))
        self.tasks.append(("enter", target_class))
        return "Loading from {} to {}".format(slot, targetslot)

    def action_stop(self):
        self.running = False
        return "Stopped"

    def action_resume(self):
        self.task_stop()
        return "Running"

    def action_park(self):
        self.running = True
        self.task = None
        self.tasks.clear()
        self.tasks.append(("goto", self.slots["s0000"]))
        self.tasks.append(("stop", self.pickers["p"]))
        return "Parking"


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
      <form action="/stop" target="hiddenFrame">
        <input type="submit" value="stop">
      </form>
      <form action="/resume" target="hiddenFrame">
        <input type="submit" value="resume">
      </form>
      <form action="/park" target="hiddenFrame">
        <input type="submit" value="park">
      </form>
    </div>

  </div>

</div>

    </body>
    </html>

    """
    return web.Response(text=text.strip(), content_type="text/html")


async def sim_runner(app):
    # your infinite loop here, for example:
    while True:
        app["tape_library"].move()
        await asyncio.sleep(1)


async def map_page1(request):

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
        web.get("/{name}", handle),
    ]
)

if __name__ == "__main__":
    web.run_app(app)
