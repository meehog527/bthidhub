import asyncio
import asyncio_glib
import os
import signal
import time

from gmqtt import Client as MQTTClient

class MQTTCli:
    def __init__(self, loop: asyncio.AbstractEventLoop, device_registry):
        self.loop = loop
        self.device_registry = device_registry
        self.client = MQTTClient("client-id")

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.client.on_subscribe = self.on_subscribe

    async def connect():
        user="homeassistant"
        pw="oochi8eengehuYohgeBu1foobooceeZ7to5ieng7pis8saephaetah0hoaphiK3F"
        broker_host = "192.168.50.95"
        self.client.set_auth_credentials(user, pw)
        await self.client.connect(broker_host)

    def on_connect(client, flags, rc, properties):
        print('Connected')
        self.client.subscribe('home-assistant/command', qos=0)

    def on_message(client, topic, payload, qos, properties):
        print('RECV MSG:', payload)
        device_registry.bluetooth_devices.send_message(payload, True, False)
        publish('home-assistant/response', payload, qos=1)
        
    def on_disconnect(client, packet, exc=None):
        print('Disconnected')

    def on_subscribe(client, mid, qos, properties):
        print('SUBSCRIBED')

    def ask_exit(*args):
        STOP.set()
