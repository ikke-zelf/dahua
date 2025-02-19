"""Dahua API Client."""
import logging
import socket
import asyncio
import aiohttp
import async_timeout
from custom_components.dahua.const import STREAM_MAIN, STREAM_SUB

from .digest import DigestAuth

_LOGGER: logging.Logger = logging.getLogger(__package__)

TIMEOUT_SECONDS = 5
SECURITY_LIGHT_TYPE = 1
SIREN_TYPE = 2


class DahuaClient:
    """
    DahuaClient is the client for accessing Dahua IP Cameras. The APIs were discovered from the "API of HTTP Protocol Specification" V2.76 2019-07-25 document
    and from inspecting the camera's HTTP UI request/responses.

    events is the list of events used to monitor on the camera (For example, motion detection)
    """

    def __init__(
            self,
            username: str,
            password: str,
            address: str,
            port: int,
            rtsp_port: int,
            session: aiohttp.ClientSession
    ) -> None:
        self._username = username
        self._password = password
        self._address = address
        self._session = session
        self._port = port
        self._rtsp_port = rtsp_port
        self._base = "http://{0}:{1}".format(address, port)

    def get_rtsp_stream_url(self, channel: int, subtype: int) -> str:
        """
        Returns the RTSP url for the supplied subtype (subtype is 0=Main stream, 1=Sub stream)
        """
        url = "rtsp://{0}:{1}@{2}:{3}/cam/realmonitor?channel={4}&subtype={5}".format(
            self._username,
            self._password,
            self._address,
            self._rtsp_port,
            channel,
            subtype,
        )
        return url

    async def async_get_snapshot(self, channel: int) -> bytes:
        """
        Takes a snapshot of the camera and returns the binary jpeg data
        """
        url = "/cgi-bin/snapshot.cgi?channel={0}".format(channel)
        return await self.get_bytes(url)

    async def async_get_system_info(self) -> dict:
        """
        Get system info data from the getSystemInfo API. Example response:

        appAutoStart=true
        deviceType=IPC-HDW5831R-ZE
        hardwareVersion=1.00
        processor=S3LM
        serialNumber=4X7C5A1ZAG21L3F
        updateSerial=IPC-HDW5830R-Z
        updateSerialCloudUpgrade=IPC-HDW5830R-Z:07:01:08:70:52:00:09:0E:03:00:04:8F0:00:00:00:00:00:02:00:00:600
        """
        url = "/cgi-bin/magicBox.cgi?action=getSystemInfo"
        return await self.get(url)

    async def get_software_version(self) -> dict:
        """
        get_software_version returns the device software version (also known as the firmware version). Example response:
        version=2.800.0000016.0.R,build:2020-06-05
        """
        url = "/cgi-bin/magicBox.cgi?action=getSoftwareVersion"
        return await self.get(url)

    async def get_machine_name(self) -> dict:
        """
        get_machine_name returns the device name. Example response:
        name=FrontDoorCam
        """
        url = "/cgi-bin/magicBox.cgi?action=getMachineName"
        return await self.get(url)

    async def get_vendor(self) -> dict:
        """
        get_vendor returns the vendor. Example response:
        vendor=Dahua
        """
        url = "/cgi-bin/magicBox.cgi?action=getVendor"
        return await self.get(url)

    async def async_get_coaxial_control_io_status(self) -> dict:
        """
        async_get_coaxial_control_io_status returns the the current state of the speaker and white light.
        Note that the "white light" here seems to also work for cameras that have the red/blue flashing alarm light
        like the IPC-HDW3849HP-AS-PV.

        Example response:

        status.status.Speaker=Off
        status.status.WhiteLight=Off
        """
        url = "/cgi-bin/coaxialControlIO.cgi?action=getStatus&channel=1"
        return await self.get(url)

    async def async_get_lighting_v2(self) -> dict:
        """
        async_get_lighting_v2 will fetch the status of the camera light (also known as the illuminator)
        NOTE: this is not the same as the infrared (IR) light. This is the white visible light on the camera
        Note all cameras have this feature.

        Example response:
        table.Lighting_V2[0][2][0].Correction=50
        table.Lighting_V2[0][2][0].LightType=WhiteLight
        table.Lighting_V2[0][2][0].MiddleLight[0].Angle=50
        table.Lighting_V2[0][2][0].MiddleLight[0].Light=100
        table.Lighting_V2[0][2][0].Mode=Manual
        table.Lighting_V2[0][2][0].PercentOfMaxBrightness=100
        table.Lighting_V2[0][2][0].Sensitive=3
        """
        url = "/cgi-bin/configManager.cgi?action=getConfig&name=Lighting_V2"
        return await self.get(url)

    async def async_get_machine_name(self) -> dict:
        """
        async_get_lighting_v1 will fetch the status of the IR light (InfraRed light)

        Example response:
        table.General.LocalNo=8
        table.General.LockLoginEnable=false
        table.General.LockLoginTimes=3
        table.General.LoginFailLockTime=1800
        table.General.MachineName=Cam4
        table.General.MaxOnlineTime=3600
        """
        url = "/cgi-bin/configManager.cgi?action=getConfig&name=General"
        return await self.get(url)

    async def async_common_config(self, profile_mode) -> dict:
        """
        async_common_config will fetch the status of the IR light (InfraRed light) and motion detection status (if it is
        enabled or not)
        profile_mode: = 0=day, 1=night, 2=normal scene

        Example response:
        table.Lighting[0][0].Correction=50
        table.Lighting[0][0].MiddleLight[0].Angle=50
        table.Lighting[0][0].MiddleLight[0].Light=50
        table.Lighting[0][0].Mode=Auto
        table.Lighting[0][0].Sensitive=3
        """
        url = "/cgi-bin/configManager.cgi?action=getConfig&name=MotionDetect&action=getConfig&name=Lighting[0][{0}]".format(
            profile_mode
        )
        return await self.get(url)

    async def async_get_config(self, name) -> dict:
        """ async_get_config gets a config by name """
        # example name=Lighting[0][0]
        url = "/cgi-bin/configManager.cgi?action=getConfig&name={0}".format(name)
        return await self.get(url)

    async def async_set_lighting_v1(self, enabled: bool, brightness: int) -> dict:
        """ async_get_lighting_v1 will turn the IR light (InfraRed light) on or off """
        # on = Manual, off = Off
        mode = "Manual"
        if not enabled:
            mode = "Off"
        return await self.async_set_lighting_v1_mode(mode, brightness)

    async def async_set_lighting_v1_mode(self, mode: str, brightness: int) -> dict:
        """
        async_set_lighting_v1_mode will set IR light (InfraRed light) mode and brightness
        Mode should be one of: Manual, Off, or Auto
        Brightness should be between 0 and 100 inclusive. 100 being the brightest
        """

        if mode.lower() == "on":
            mode = "Manual"
        # Dahua api expects the first char to be capital
        mode = mode.capitalize()

        url = "/cgi-bin/configManager.cgi?action=setConfig&Lighting[0][0].Mode={0}&Lighting[0][0].MiddleLight[0].Light={1}".format(
            mode, brightness
        )
        return await self.get(url)

    async def async_set_video_profile_mode(self, mode: str):
        """
        async_set_video_profile_mode will set camera's profile mode to day or night
        Mode should be one of: Day or Night
        """

        if mode.lower() == "night":
            mode = "1"
        else:
            # Default to "day", which is 0
            mode = "0"

        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoInMode[0].Config[0]={0}".format(mode)
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not set video profile mode")

    async def async_enable_channel_title(self, channel: int, enabled: bool, ):
        """ async_set_enable_channel_title will enable or disables the camera's channel title overlay """
        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoWidget[{0}].ChannelTitle.EncodeBlend={1}".format(
            channel, str(enabled).lower()
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could enable/disable channel title")

    async def async_enable_time_overlay(self, channel: int, enabled: bool):
        """ async_set_enable_time_overlay will enable or disables the camera's time overlay """
        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoWidget[{0}].TimeTitle.EncodeBlend={1}".format(
            channel, str(enabled).lower()
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not enable/disable time overlay")

    async def async_enable_text_overlay(self, channel: int, group: int, enabled: bool):
        """ async_set_enable_text_overlay will enable or disables the camera's text overlay """
        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoWidget[{0}].CustomTitle[{1}].EncodeBlend={2}".format(
            channel, group, str(enabled).lower()
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not enable/disable text overlay")

    async def async_enable_custom_overlay(self, channel: int, group: int, enabled: bool):
        """ async_set_enable_custom_overlay will enable or disables the camera's custom overlay """
        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoWidget[{0}].UserDefinedTitle[{1}].EncodeBlend={2}".format(
            channel, group, str(enabled).lower()
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not enable/disable customer overlay")

    async def async_set_service_set_channel_title(self, channel: int, text1: str, text2: str):
        """ async_set_service_set_channel_title sets the channel title """
        text = '|'.join(filter(None, [text1, text2]))
        url = "/cgi-bin/configManager.cgi?action=setConfig&ChannelTitle[{0}].Name={1}".format(
            channel, text
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not set text")

    async def async_set_service_set_text_overlay(self, channel: int, group: int, text1: str, text2: str, text3: str,
                                                 text4: str):
        """ async_set_service_set_text_overlay sets the video text overlay """
        text = '|'.join(filter(None, [text1, text2, text3, text4]))
        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoWidget[{0}].CustomTitle[{1}].Text={2}".format(
            channel, group, text
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not set text")

    async def async_set_service_set_custom_overlay(self, channel: int, group: int, text1: str, text2: str):
        """ async_set_service_set_custom_overlay sets the customer overlay on the video"""
        text = '|'.join(filter(None, [text1, text2]))
        url = "/cgi-bin/configManager.cgi?action=setConfig&VideoWidget[{0}].UserDefinedTitle[{1}].Text={2}".format(
            channel, group, text
        )
        value = await self.get(url)
        if "OK" not in value and "ok" not in value:
            raise Exception("Could not set text")

    async def async_set_lighting_v2(self, enabled: bool, brightness: int, profile_mode: str) -> dict:
        """
        async_set_lighting_v2 will turn on or off the white light on the camera. If turning on, the brightness will be used.
        brightness is in the range of 0 to 100 inclusive where 100 is the brightest.
        NOTE: this is not the same as the infrared (IR) light. This is the white visible light on the camera

        profile_mode: 0=day, 1=night, 2=scene
        """

        # on = Manual, off = Off
        mode = "Manual"
        if not enabled:
            mode = "Off"
        url = "/cgi-bin/configManager.cgi?action=setConfig&Lighting_V2[0][{0}][0].Mode={1}&Lighting_V2[0][{2}][0].MiddleLight[0].Light={3}".format(
            profile_mode, mode, profile_mode, brightness
        )
        _LOGGER.debug("Turning light on: %s", url)
        return await self.get(url)

    async def async_get_video_in_mode(self) -> dict:
        """
        async_get_video_in_mode will return the profile mode (day/night)
        0 means config for day,
        1 means config for night, and
        2 means config for normal scene.

        table.VideoInMode[0].Config[0]=2
        table.VideoInMode[0].Mode=0
        table.VideoInMode[0].TimeSection[0][0]=0 00:00:00-24:00:00
        """

        url = "/cgi-bin/configManager.cgi?action=getConfig&name=VideoInMode"
        return await self.get(url)

    async def async_set_coaxial_control_state(self, dahua_type: int, enabled: bool) -> dict:
        """
        async_set_lighting_v2 will turn on or off the white light on the camera.

        Type=1 -> white light on the camera. this is not the same as the infrared (IR) light. This is the white visible light on the camera
        Type=2 -> siren. The siren will trigger for 10 seconds or so and then turn off. I don't know how to get the siren to play forever
        NOTE: this is not the same as the infrared (IR) light. This is the white visible light on the camera
        """

        # on = 1, off = 0
        io = "1"
        if not enabled:
            io = "2"

        url = "/cgi-bin/coaxialControlIO.cgi?action=control&channel=0&info[0].Type={0}&info[0].IO={1}".format(
            dahua_type, io)
        _LOGGER.debug("Setting coaxial control state to %s: %s", io, url)
        return await self.get(url)

    async def async_set_disarming_linkage(self, enabled: bool) -> dict:
        """
        async_set_disarming_linkage will set the camera's disarming linkage (Event -> Disarming in the UI)
        """

        value = "false"
        if enabled:
            value = "true"

        url = "/cgi-bin/configManager.cgi?action=setConfig&DisableLinkage[0].Enable={0}".format(value)
        return await self.get(url)

    async def async_set_record_mode(self, mode: str) -> dict:
        """
        async_set_record_mode sets the record mode.
        mode should be one of: auto, manual, or off
        """

        if mode.lower() == "auto":
            mode = "0"
        elif mode.lower() == "manual" or mode.lower() == "on":
            mode = "1"
        elif mode.lower() == "off":
            mode = "2"
        url = "/cgi-bin/configManager.cgi?action=setConfig&RecordMode[0].Mode={0}".format(mode)
        _LOGGER.debug("Setting record mode: %s", url)
        return await self.get(url)

    async def async_get_disarming_linkage(self) -> dict:
        """
        async_get_disarming_linkage will return true if the disarming linkage (Event -> Disarming in the UI) is enabled

        returns
        table.DisableLinkage.Enable=false
        """

        url = "/cgi-bin/configManager.cgi?action=getConfig&name=DisableLinkage"
        return await self.get(url)

    async def enable_motion_detection(self, enabled: bool) -> dict:
        """
        enable_motion_detection will either enable or disable motion detection on the camera depending on the supplied value
        """
        url = "/cgi-bin/configManager.cgi?action=setConfig&MotionDetect[0].Enable={0}&MotionDetect[0].DetectVersion=V3.0".format(
            str(enabled).lower())
        response = await self.get(url)

        if "OK" in response:
            return response

        # Some older cameras do not support the above API, so try this one
        url = "/cgi-bin/configManager.cgi?action=setConfig&MotionDetect[0].Enable={0}".format(str(enabled).lower())
        response = await self.get(url)

        return response

    async def stream_events(self, on_receive, events: list):
        """
        enable_motion_detection will either enable or disable motion detection on the camera depending on the supplied value

        All: Use the literal word "All" to get back all events.. or pick and choose from the ones below
        VideoMotion: motion detection event
        VideoMotionInfo: fires when there's motion. Not really sure what it is for
        NewFile:
        SmartMotionHuman: human smart motion detection
        SmartMotionVehicle：Vehicle smart motion detection
        IntelliFrame: I don't know what this is
        VideoLoss: video loss detection event
        VideoBlind: video blind detection event.
        AlarmLocal: alarm detection event.
        CrossLineDetection: tripwire event
        CrossRegionDetection: intrusion event
        LeftDetection: abandoned object detection
        TakenAwayDetection: missing object detection
        VideoAbnormalDetection: scene change event
        FaceDetection: face detect event
        AudioMutation: intensity change
        AudioAnomaly: input abnormal
        VideoUnFocus: defocus detect event
        WanderDetection: loitering detection event
        RioterDetection: People Gathering event
        ParkingDetection: parking detection event
        MoveDetection: fast moving event
        StorageNotExist: storage not exist event.
        StorageFailure: storage failure event.
        StorageLowSpace: storage low space event.
        AlarmOutput: alarm output event.
        InterVideoAccess: I don't know what this is
        NTPAdjustTime: NTP time updates?
        TimeChange: Some event for time changes, related to NTPAdjustTime
        MDResult: motion detection data reporting event. The motion detect window contains 18 rows and 22 columns. The event info contains motion detect data with mask of every row.
        HeatImagingTemper: temperature alarm event
        CrowdDetection: crowd density overrun event
        FireWarning: fire warning event
        FireWarningInfo: fire warning specific data info

        In the example, you can see most event info is like "Code=eventcode; action=Start;
        index=0", but for some specific events, they will contain an another parameter named
        "data", the event info is like "Code=eventcode; action=Start; index=0; data=datainfo",
        the datainfo's fomat is JSON(JavaScript Object Notation). The detail information about
        the specific events and datainfo are listed in the appendix below this table.

        Heartbeat: integer, range is [1,60],unit is second.If the URL contains this parameter,
        and the value is 5, it means every 5 seconds the device should send the heartbeat
        message to the client,the heartbeat message are "Heartbeat".
        Note: Heartbeat message must be sent before heartbeat timeout
        """
        # Use codes=[All] for all codes
        codes = ",".join(events)
        url = "{0}/cgi-bin/eventManager.cgi?action=attach&codes=[{1}]&heartbeat=2".format(self._base, codes)
        if self._username is not None and self._password is not None:
            response = None
            try:
                auth = DigestAuth(self._username, self._password, self._session)
                response = await auth.request("GET", url)
                response.raise_for_status()

                # https://docs.aiohttp.org/en/stable/streams.html
                async for data, _ in response.content.iter_chunks():
                    on_receive(data)
            except Exception as exception:
                raise ConnectionError() from exception
            finally:
                if response is not None:
                    response.close()

    @staticmethod
    async def parse_dahua_api_response(data: str) -> dict:
        """
        Dahua APIs return back text that looks like this:

        key1=value1
        key2=value2

        We'll convert that to a dictionary like {"key1":"value1", "key2":"value2"}
        """
        lines = data.splitlines()
        data_dict = {}
        for line in lines:
            parts = line.split("=", 1)
            if len(parts) == 2:
                data_dict[parts[0]] = parts[1]
            else:
                # We didn't get a key=value. We just got a key. Just stick it in the dictionary and move on
                data_dict[parts[0]] = line
        return data_dict

    async def get_bytes(self, url: str) -> bytes:
        """Get information from the API. This will return the raw response and not process it"""
        try:
            async with async_timeout.timeout(TIMEOUT_SECONDS):
                response = None
                try:
                    auth = DigestAuth(self._username, self._password, self._session)
                    response = await auth.request("GET", self._base + url)
                    response.raise_for_status()

                    return await response.read()
                finally:
                    if response is not None:
                        response.close()

        except asyncio.TimeoutError as exception:
            _LOGGER.error("Timeout error fetching information from %s - %s", url, exception)
        except (KeyError, TypeError) as exception:
            _LOGGER.error("Error parsing information from %s - %s", url, exception)
        except (aiohttp.ClientError, socket.gaierror) as exception:
            _LOGGER.error("Error fetching information from %s - %s", url, exception)
        except Exception as exception:  # pylint: disable=broad-except
            _LOGGER.error("Something really wrong happened! - %s", exception)

    async def get(self, url: str) -> dict:
        """Get information from the API."""
        url = self._base + url
        data = {}
        try:
            async with async_timeout.timeout(TIMEOUT_SECONDS):
                response = None
                try:
                    auth = DigestAuth(self._username, self._password, self._session)
                    response = await auth.request("GET", url)
                    response.raise_for_status()
                    data = await response.text()
                    return await self.parse_dahua_api_response(data)
                finally:
                    if response is not None:
                        response.close()
        except asyncio.TimeoutError as exception:
            _LOGGER.error("TimeoutError fetching information from %s - %s", url, exception)
        except (KeyError, TypeError) as exception:
            _LOGGER.error("TypeError parsing information from %s - %s", url, exception)
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise exception
        except Exception as exception:  # pylint: disable=broad-except
            _LOGGER.error("Something really wrong happened! - %s", exception)

    @staticmethod
    def to_subtype(stream_name: str) -> int:
        """
        Given a stream name (Main or Sub) returns the subtype index. The index is what the API uses
        """
        if stream_name == STREAM_MAIN:
            return 0
        elif stream_name == STREAM_SUB:
            return 1

        # Just default to the main stream
        return 0

    @staticmethod
    def to_stream_name(subtype: int) -> str:
        """
        Given the subtype, returns the stream name (Main or Sub)
        """
        if subtype == 1:
            return STREAM_SUB

        # Just default to the main stream
        return STREAM_MAIN