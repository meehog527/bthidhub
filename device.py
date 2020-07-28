# Copyright (c) 2020 ruundii. All rights reserved.

from dasbus.connection import SystemMessageBus
import asyncio
import socket
from a1314_message_filter import A1314MessageFilter
from typing import List

OBJECT_MANAGER_INTERFACE = 'org.freedesktop.DBus.ObjectManager'
DEVICE_INTERFACE = 'org.bluez.Device1'
PROPERTIES_INTERFACE = 'org.freedesktop.DBus.Properties'
INPUT_DEVICE_INTERFACE = 'org.bluez.Input1'
INPUT_HOST_INTERFACE = 'org.bluez.InputHost1'

filters_registry = {"A1314":A1314MessageFilter()}
device_filters = {"/org/bluez/hci0/dev_28_CF_E9_6A_05_93":"A1314"}


class Device:
    def __init__(self, bus : SystemMessageBus, device_registry, object_path, is_host,  control_socket_path, interrupt_socket_path):
        self.device = bus.get_proxy(service_name="org.bluez", object_path=object_path, interface_name=DEVICE_INTERFACE)
        self.props = bus.get_proxy(service_name="org.bluez", object_path=object_path, interface_name=PROPERTIES_INTERFACE)
        self.props.PropertiesChanged.connect(self.device_connected_state_changed)

        self.bus = bus
        self.device_registry = device_registry
        self.object_path = object_path
        self.is_host = is_host
        self.control_socket_path = control_socket_path
        self.control_socket = None
        self.interrupt_socket_path = interrupt_socket_path
        self.interrupt_socket = None
        self.sockets_connected = False

        if not is_host and object_path in device_filters and device_filters[object_path] in filters_registry:
            self.filter = filters_registry[device_filters[object_path]]
        else:
            self.filter = None

        print("Device ",object_path," created")
        asyncio.ensure_future(self.reconcile_connected_state(1))

    async def reconcile_connected_state(self, delay):
        await asyncio.sleep(delay)
        try:
            if self.connected and not self.sockets_connected:
                await self.connect_sockets()
            elif not self.connected and self.sockets_connected:
                await self.disconnect_sockets()
        except Exception as exc:
            print("Possibly dbus error during reconcile_connected_state ",exc)

    async def connect_sockets(self):
        if self.sockets_connected or self.control_socket_path is None or self.interrupt_socket_path is None:
            return
        print("Connecting sockets for ",self.object_path)
        if not self.connected:
            print("Device is not connected. No point connecting sockets. Skipping.")
        try:
            self.control_socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.control_socket.connect(self.control_socket_path)
            self.control_socket.setblocking(False)

            self.interrupt_socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.interrupt_socket.connect(self.interrupt_socket_path)
            self.interrupt_socket.setblocking(False)
            self.sockets_connected = True
            if(self.is_host):
                self.device_registry.connected_hosts.append(self)
            else:
                self.device_registry.connected_devices.append(self)
            print("Connected sockets for ",self.object_path)
            asyncio.ensure_future(self.loop_of_fun(True))
            asyncio.ensure_future(self.loop_of_fun(False))
        except Exception as err:
            print("Error while connecting sockets for ",self.object_path,". Will retry in a sec", err)
            try:
                self.control_socket.close()
                self.interrupt_socket.close()
            except:
                pass
            await asyncio.sleep(1)
            asyncio.ensure_future(self.connect_sockets())

    def disconnect_sockets(self):
        if self.control_socket is not None:
            self.control_socket.close()
            self.control_socket = None
        if self.interrupt_socket is not None:
            self.interrupt_socket.close()
            self.interrupt_socket = None
        if(self.is_host and self in self.device_registry.connected_hosts):
            self.device_registry.connected_hosts.remove(self)
        elif self in self.device_registry.connected_devices:
            self.device_registry.connected_devices.remove(self)
        self.sockets_connected = False

        print("Disconnected  sockets for ",self.object_path)


    async def loop_of_fun(self, is_ctrl):
        loop = asyncio.get_event_loop()
        sock = self.control_socket if is_ctrl else self.interrupt_socket
        while sock is not None:
            try:
                msg = await loop.sock_recv(sock,255)
            except Exception:
                print("Cannot read data from socket. ", self.object_path ,"Closing sockets")
                if self is not None:
                    try:
                        await self.disconnect_sockets()
                    except:
                        print("Error while disconnecting sockets")
                print("Arranging reconnect")
                asyncio.ensure_future(self.reconcile_connected_state(1))
                break
            if filter is not None:
                if self.filter is not None:
                    msg = self.filter.filter_message_to_host(msg)
            if msg is None or len(msg)==0:
                continue
            await self.device_registry.send_message(msg, not self.is_host, is_ctrl)
            sock = self.control_socket if is_ctrl else self.interrupt_socket


    @property
    def name(self):
        return self.device.Name

    @property
    def alias(self):
        return self.device.Alias

    @property
    def connected(self):
        return self.device.Connected

    def __eq__(self, other):
        return self.object_path == other.object_path

    def device_connected_state_changed(self, arg1,arg2, arg3):
        print("device_connected_state_changed")
        asyncio.ensure_future(self.reconcile_connected_state(1))

    def finalise(self):
        self.props.PropertiesChanged.disconnect(self.device_connected_state_changed)
        self.control_socket_path = None
        self.interrupt_socket_path = None
        #close sockets
        self.disconnect_sockets()
        print("Device ",self.object_path," finalised")


    def __del__(self):
        print("Device ",self.object_path," removed")

class DeviceRegistry:
    def __init__(self, bus:SystemMessageBus):
        self.bus = bus
        self.all = {}
        self.connected_hosts = []
        self.connected_devices = []

    def add_devices(self):
        print("Adding all devices")
        om = self.bus.get_proxy(service_name= "org.bluez", object_path="/", interface_name=OBJECT_MANAGER_INTERFACE)
        objs = om.GetManagedObjects()

        for obj in list(objs):
            if INPUT_HOST_INTERFACE in objs[obj]:
                self.add_device(obj, True)

            elif INPUT_DEVICE_INTERFACE in objs[obj]:
                self.add_device(obj, False)


    def add_device(self, device_object_path, is_host):
        if device_object_path in self.all:
            print("Device ", device_object_path, " already exist. Cannot add. Skipping.")
            return
        p = self.bus.get_proxy(service_name="org.bluez", object_path=device_object_path, interface_name=INPUT_HOST_INTERFACE if is_host else INPUT_DEVICE_INTERFACE)
        device = Device(self.bus, self, device_object_path, is_host, p.SocketPathCtrl, p.SocketPathIntr)
        self.all[device_object_path] = device

    def remove_devices(self):
        print("Removing all devices")
        while len(self.all) >0:
            self.remove_device(list(self.all)[0])

    def remove_device(self, device_object_path):
        if device_object_path not in self.all:
            return #no such device
        device = self.all[device_object_path]
        del self.all[device_object_path]
        list = self.connected_hosts if device.is_host else self.connected_devices
        if device in list:
            list.remove(device)
        device.finalise()
        del device



    async def send_message(self, msg, send_to_hosts, is_control_channel):
        targets: List[Device] = self.connected_hosts if send_to_hosts else self.connected_devices
        loop = asyncio.get_event_loop()
        for target in list(targets):
            tm = target.filter.filter_message_from_host(msg) if target.filter is not None else msg
            try:
                await loop.sock_sendall(target.control_socket if is_control_channel else target.interrupt_socket , tm)
            except Exception:
                print("Cannot send data to socket of ",target.object_path,". Closing")
                if target is not None:
                    try:
                        await target.disconnect_sockets()
                    except:
                        print("Error while trying to disconnect sockets")
                asyncio.ensure_future(target.reconcile_connected_state(1))


