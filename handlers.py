# Handlers

import json
import logging

from aiohttp import web


def tape_library_handler_wrapper(
    request,
    action_name,
    required_params=None,
    optional_params=None,
    skip_lock_check=False,
):
    """This wrapper performs error handling for the API calls.

    Raises
    ------
    Multiple exceptions

    see: https://docs.aiohttp.org/en/latest/web_exceptions.html
    """
    # Check parameters
    if required_params is not None:
        for param in required_params:
            if param in request.query:
                if not request.query[param]:
                    error = {
                        "error": {
                            "description": "empty parameter",
                            "parameter": param,
                            "reason": "empty",
                            "type": "parameter",
                        }
                    }
                    raise web.HTTPUnprocessableEntity(text=json.dumps(error))
            else:
                error = {
                    "error": {
                        "description": "missing parameter",
                        "parameter": param,
                        "reason": "undefined",
                        "type": "parameter",
                    }
                }
                raise web.HTTPUnprocessableEntity(text=json.dumps(error))

    library = request.app["tape_library"]
    # Check that library is not locked
    if not library.running and not skip_lock_check:
        error = {
            "error": {
                "description": "Library is locked",
                "reason": "locked",
                "type": "lock",
            }
        }
        raise web.HTTPForbidden(text=json.dumps(error))
    # Check library queue
    if library.check_queue_max_depth_reached():
        error = {
            "error": {
                "description": "to many requests in progress",
                "reason": "full",
                "type": "taskqueue",
            }
        }
        raise web.HTTPTooManyRequests(text=json.dumps(error))
    # Check if action is available, run it, catch errors if any
    if hasattr(library, "action_" + action_name):
        try:
            data = getattr(library, "action_" + action_name)(**request.query)
        except web.HTTPException:
            raise
        except Exception as excpt:
            logging.exception(action_name)
            error = {
                "error": {
                    "description": str(excpt),
                    "reason": "internal",
                    "type": "server",
                }
            }
            raise web.HTTPInternalServerError(text=json.dumps(error))

    else:
        error = {
            "error": {
                "description": "no such method",
                "reason": "nosuch",
                "type": "method",
            }
        }
        raise web.HTTPNotImplemented(text=json.dumps(error))
    return web.json_response(data)


# Handlers that represent the system we simulate.
async def load_handle(request):
    """
    ---
    description: Load media from slot to drive.
    tags:
    - mtx
    parameters:
       - in: query
         name: drive
         schema:
           type: string
         required: true
         description: The ID of the drive.
       - in: query
         name: slot
         schema:
           type: string
         required: true
         description: The ID of the slot.
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    return tape_library_handler_wrapper(
        request, "load", required_params=["slot", "drive"]
    )


async def unload_handle(request):
    """
    ---
    description: Unload media from drive to slot.
    tags:
    - mtx
    parameters:
       - in: query
         name: drive
         schema:
           type: string
         required: true
         description: The ID of the drive.
       - in: query
         name: slot
         schema:
           type: string
         required: true
         description: The ID of the slot.
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    return tape_library_handler_wrapper(
        request, "unload", required_params=["drive", "slot"]
    )


async def transfer_handle(request):
    """
    ---
    description: Move media from source-slot to target-slot.
    tags:
    - mtx
    parameters:
       - in: query
         name: source
         schema:
           type: string
         required: true
         description: The ID of the source slot.
       - in: query
         name: target
         schema:
           type: string
         required: true
         description: The ID of the target slot.
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    return tape_library_handler_wrapper(
        request, "transfer", required_params=["source", "target"]
    )


async def park_handle(request):
    """
    ---
    description: Move the picker head to a safe position and lock the unit.
    tags:
    - mtx
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    return tape_library_handler_wrapper(request, "park")


async def scan_handle(request):
    """
    ---
    description: Perform inventory scan on a slot. Move the picker to the slot
      and barcode scan the tape.
    tags:
    - mtx
    parameters:
       - in: query
         name: slot
         schema:
           type: string
         required: true
         description: The ID of the slot to scan.
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    return tape_library_handler_wrapper(request, "scan", required_params=["slot"])


async def inventory_handle(request):
    """
    ---
    description: Return the known inventory. Use scan command to scan a slot.
      For each slot either the tapeid, true, false, or null is returned. null
      indicates that the slot has not been scanned. false indicate that the
      slot has no tape and true that the slot has a tape but we dont know the ID.
      A real tape library might remember a tapeid as it moves from slot to drive, but the
      simulator is kept dump to simulate the bare minimum required.
    tags:
    - info
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
    """
    return tape_library_handler_wrapper(request, "inventory", skip_lock_check=True)


async def sensors_handle(request):
    """
    ---
    summary: sensor values
    description: Return sensor values.
    tags:
    - info
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    # TODO(MS): Maybe allow some filter. It could be quite a bit of info.
    return tape_library_handler_wrapper(request, "sensors", skip_lock_check=True)


async def config_handle(request):
    """
    ---
    summary: get/set config
    description: Return configuration, configuration can also be set.
    tags:
    - info
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    return tape_library_handler_wrapper(request, "config", skip_lock_check=True)


async def state_handle(request):
    """
    ---
    summary: state
    description: Return the library state.
    tags:
    - info
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
    """
    return tape_library_handler_wrapper(request, "state", skip_lock_check=True)


async def lock_handle(request):
    """
    ---
    summary: lock tape library
    description: Lock the tape library. No actions will be allowed until unlocked.
      This action clears the internal work queue.
    tags:
    - mtx
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
    """
    return tape_library_handler_wrapper(request, "lock", skip_lock_check=True)


async def unlock_handle(request):
    """
    ---
    summary: Unlock tape library
    description: Unlock the tape library. Has no side effect if already unlocked.
    tags:
    - mtx
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
    """
    # TODO: Should unlock have a clear_queue argument?
    return tape_library_handler_wrapper(request, "unlock", skip_lock_check=True)
