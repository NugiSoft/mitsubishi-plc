from datetime import datetime
import logging
from operator import xor
import re
import socket
from functools import reduce


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# FINS header constants
RESPONSE_WAIT = '0'
ICF_COMMAND = '80'
ICF_RESPONSE = 'C0'
RSV = '00'
GCT = '02'
DNA = '00'
DA1 = '00'
DA2 = '00'
SNA = '00'
SA1 = '00'
SA2 = '00'
SID = '00'

FINS_HEADER = ''.join((RESPONSE_WAIT, ICF_COMMAND, RSV, GCT, DNA, DA1, DA2, SNA,
                       SA1, SA2, SID))
ADDRESS_BYTES = ''.join((DNA, DA1, DA2, SNA, SA1, SA2, SID))

# FINS commands
MEMORY_AREA_READ = '0101'
MEMORY_AREA_WRITE = '0102'
CLOCK_READ = '0701'
CLOCK_WRITE = '0702'

# Memory area codes
CIO_BIT = '30'
WR_BIT = '31'
HR_BIT = '32'
AR_BIT = '33'
CIO_WORD = 'B0'
WR_WORD = 'B1'
HR_WORD = 'B2'
AR_WORD = 'B3'
DM_BIT = '02'
DM_WORD = '82'

# The size of items are dependent on the memory area. This is a mapping between
# the memory area and the size of items in bytes returned in the memory read
# area command.
ITEM_BYTE_SIZE = {CIO_BIT: 1,
                  WR_BIT: 1,
                  HR_BIT: 1,
                  AR_BIT: 1,
                  CIO_WORD: 2,
                  WR_WORD: 2,
                  HR_WORD: 2,
                  AR_WORD: 2,
                  DM_BIT: 1,
                  DM_WORD: 2}

TCP_TIMEOUT = 2


class FINS(object):

    """This class implements various FINS commands.

    The class is instatiated with a connection object that allows transmission
    of FINS commands over some channel.

    Supported FINS commands are:
        Memory area read (01 01)
        Memory area write (01 02)
        Clock read (07 01)
        Clock write (07 02)
    """

    def __init__(self, connection):
        """`connection` is an object that supports the methods `send(data)` and
        `receive()`. `send(data)` should return True when data has been
        successfully sent and `receive()` should return an ASCII FINS response.
        As long as these methods are supported, it does not matter how the
        underlying connection is implemented. For example, `connection` may send
        data using Host Link over serial over TCP/IP.
        """
        self.connection = connection

    def send(self, command_code, text='', retries=3):
        """Construct a FINS command from the specified `command_code` and
        `text` and send it over the connection. If a valid response is received,
        it is stripped of FINS headers and verified. `retries` attempts will be
        made to get a valid response before giving up.

        The text part of the FINS response command is returned.
        """
        fins_command = FINS_HEADER + command_code + text
        attempts = 0
        while attempts < retries:
            attempts += 1
            if self.connection.send(fins_command):
                response = self.connection.receive()
                if response is not None:
                    text = strip_fins_response(response, command_code)
                    if text is not None:
                        return text
        logger.error('Did not receive a valid FINS response command after %s '
                     'attempts', attempts)

    def memory_area_read(self, memory_area_code, address_word, address_bit=0,
                         num_items=1, bcd=False):
        """Returns a list of integers (`num_items` in length) from the
        specified memory location.

        The memory location is made up of
            `memory_area_code` - representing an area in memory
            `address_word` - the address of the first word to read
            `address_bit` - the first bit in the word to read
        When reading words, `address_bit` must be set to 0.

        Set `bcd` to True to interpret the response as BCD (binary-coded
        decimal.)

        `num_items`, `address_word` and `address_bit` must be integers. If
        `num_items` is 0, an empty list will be returned.
        """
        command_text = ''.join((memory_area_code,
                                hex_string(address_word, bytes=2),
                                hex_string(address_bit),
                                hex_string(num_items, bytes=2)))
        text = self.send(MEMORY_AREA_READ, command_text)
        if text is not None:
            # Check that the length of `text` is what we expect. The number of
            # bytes of each item differs depending on the memory area code.
            # The byte sizes are specified in `ITEM_BYTE_SIZE`. Each item's
            # ASCII-encoded bytes are two characters long.
            item_len = ITEM_BYTE_SIZE[memory_area_code] * 2
            if num_items * item_len == len(text):
                # Separate items, still strings.
                items = [text[i:i + item_len]
                         for i in range(0, len(text), item_len)]
                base = 10 if bcd is True else 16
                # Converted to integers.
                integers = []
                for item in items:
                    try:
                        integers.append(int(item, base=base))
                    except ValueError:
                        # On error, set the integer to 0.
                        logger.warning(
                            '%s is not a base %s number, setting to 0',
                            item, base)
                        integers.append(0)
                return integers

    def memory_area_read_single(self, memory_area_code, address_word,
                                address_bit=0, bcd=False):
        """Simple wrapper around memory_area_read that just returns an single
        integer.
        """
        values = self.memory_area_read(
            memory_area_code, address_word, address_bit=address_bit,
            num_items=1, bcd=bcd)
        try:
            return values[0]
        except TypeError:
            pass

    def memory_area_write(self, memory_area_code, address_word, address_bit=0,
                          values=[], bcd=False):
        """Write integer values from iterable `values` starting at the
        specified memory location.

        Returns True on a successful write.

        The memory location is made up of
            `memory_area_code` - representing an area in memory
            `address_word` - the address of the first word to read
            `address_bit` - the first bit in the word to read
        When writing words, `address_bit` must be set to 0.

        If `values` is simply an integer (e.g. values=0xFF), then
        `values` will be treated as a single word or bit to be written.

        If `bcd` is True, the values will be converted to a BCD representation
        before being written. Note, this does not assume the given values are
        represented as BCD.
        """
        item_bytes = ITEM_BYTE_SIZE[memory_area_code]
        # Make values a list regardless of whether it is a single value or an
        # iterable.
        try:
            values = list(values)
        except TypeError:
            values = [values]
        num_items = len(values)
        # Convert values to a BCD representation if required.
        if bcd is True:
            values = (int(str(value), base=16) for value in values)
        data = ''.join(hex_string(value, bytes=item_bytes)
                       for value in values)
        command_text = ''.join((memory_area_code,
                                hex_string(address_word, bytes=2),
                                hex_string(address_bit),
                                hex_string(num_items, bytes=2),
                                data))
        text = self.send(MEMORY_AREA_WRITE, command_text)
        if text == '':
            return True

    def clock_read(self):
        """Perform a clock read command and return the response as a datetime
        object.
        """
        text = self.send(CLOCK_READ)
        if text is not None:
            try:
                clock = datetime.strptime(text[:-2], '%y%m%d%H%M%S')
                return clock
            except ValueError:
                pass

    def clock_write(self, datetime):
        """Perform a clock write command, setting the clock according to
        `datetime`. Returns True on successful clock write.
        """
        command_text = datetime.strftime('%y%m%d%H%M%S')
        text = self.send(CLOCK_WRITE, command_text)
        if text == '':
            return True


class TCPHostLinkConnection(object):

    """This class supports the sending and receiving of Host Link FINS commands
    over TCP.
    """

    def __init__(self, host, port):
        """Specify a `host` (host name or IP address) and `port` that will
        accept Host Link commands.
        """
        self.host = host
        self.port = port
        self.socket = None

    def send(self, fins_command):
        """Wrap `fins_command` in a Host Link command and send it over a TCP
        socket.

        Returns True if the FINS command was successfully sent.
        """
        hostlink_command = create_hostlink_command(fins_command)
        try:
            if self.socket is None:
                self.socket = socket.create_connection(
                    (self.host, self.port), TCP_TIMEOUT)
            payload = hostlink_command.encode('ascii') if isinstance(self.socket, socket.socket) else hostlink_command
            self.socket.sendall(payload)
            return True
        except (socket.error, socket.timeout) as e:
            logger.error('Socket send error: %s', e)
            if self.socket is not None:
                self.socket.close()
            self.socket = None

    def receive(self):
        """Receive data from a TCP socket and return the underlying FINS
        response from the Host Link response.
        """
        response = ''
        while '*\r' not in response:
            try:
                data = self.socket.recv(4096)
                if isinstance(data, bytes):
                    data = data.decode('ascii', errors='ignore')
                if data == '':
                    logger.error('Socket returned an empty string')
                    break
                response += data
            except (socket.error, socket.timeout) as e:
                logger.error('Socket receive error: %s', e)
                break
        else:
            return strip_hostlink_response(response)
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None


class UDPFinsConnection(object):
    """Koneksi FINS/UDP Binary standar Ethernet Omron (Default Port: 9600).
    Kompatibel penuh dengan class FINS di fins.py.
    """

    def __init__(self, host, port=9600, dest_node=0, src_node=1, timeout=TCP_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.dest_node = int(dest_node)
        self.src_node = int(src_node)
        self.timeout = timeout
        self.socket = None

    def send(self, fins_command):
        try:
            if self.socket is None:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.settimeout(self.timeout)
            # Hapus 1 karakter RESPONSE_WAIT ('0') di depan FINS_HEADER untuk paket binary UDP
            raw_hex = fins_command[1:]
            # Set DA1 (byte ke-4 -> hex index 8..10) & SA1 (byte ke-7 -> hex index 14..16)
            da1_hex = hex_string(self.dest_node, 1)
            sa1_hex = hex_string(self.src_node, 1)
            raw_hex = raw_hex[:8] + da1_hex + raw_hex[10:14] + sa1_hex + raw_hex[16:]
            self.socket.sendto(bytes.fromhex(raw_hex), (self.host, self.port))
            return True
        except (socket.error, socket.timeout, ValueError) as e:
            logger.error('UDP FINS send error: %s', e)
            self.close()

    def receive(self):
        if self.socket is None:
            return None
        try:
            data, _ = self.socket.recvfrom(4096)
            if not data or len(data) < 14:
                return None
            resp_hex = data.hex().upper()
            # Normalisasi 7 byte alamat (DNA..SID) menjadi ADDRESS_BYTES ('00'*7)
            # dan tambahkan prefix '00' agar cocok dengan strip_fins_response()
            normalized = '00' + resp_hex[:6] + ADDRESS_BYTES + resp_hex[20:]
            return normalized
        except (socket.error, socket.timeout) as e:
            logger.error('UDP FINS receive error: %s', e)
            return None

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None


class TCPFinsConnection(object):
    """Koneksi FINS/TCP Binary standar Ethernet Omron (Default Port: 9600).
    Melakukan handshake FINS/TCP Node Address otomatis dan kompatibel dengan class FINS.
    """

    def __init__(self, host, port=9600, timeout=TCP_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.socket = None
        self.client_node = 0
        self.server_node = 0

    def _connect_and_handshake(self):
        self.socket = socket.create_connection((self.host, self.port), self.timeout)
        self.socket.settimeout(self.timeout)
        # Handshake FINS/TCP: "FINS" + Length(12) + Command(0) + Error(0) + ClientNode(0=Auto)
        handshake_req = bytes.fromhex('46494E530000000C000000000000000000000000')
        self.socket.sendall(handshake_req)
        resp = self.socket.recv(24)
        if len(resp) < 24 or resp[:4] != b'FINS':
            raise socket.error('Invalid FINS/TCP handshake response')
        self.client_node = resp[19]
        self.server_node = resp[23]

    def send(self, fins_command):
        try:
            if self.socket is None:
                self._connect_and_handshake()
            raw_hex = fins_command[1:]
            da1_hex = hex_string(self.server_node, 1)
            sa1_hex = hex_string(self.client_node, 1)
            raw_hex = raw_hex[:8] + da1_hex + raw_hex[10:14] + sa1_hex + raw_hex[16:]
            fins_bytes = bytes.fromhex(raw_hex)
            # Header FINS/TCP untuk pengiriman frame FINS (Command = 2)
            tcp_len = len(fins_bytes) + 8
            tcp_header = b'FINS' + tcp_len.to_bytes(4, 'big') + (2).to_bytes(4, 'big') + (0).to_bytes(4, 'big')
            self.socket.sendall(tcp_header + fins_bytes)
            return True
        except (socket.error, socket.timeout, ValueError) as e:
            logger.error('TCP FINS send error: %s', e)
            self.close()

    def receive(self):
        if self.socket is None:
            return None
        try:
            data = self.socket.recv(4096)
            if not data or len(data) < 30 or data[:4] != b'FINS':
                return None
            fins_payload = data[16:]
            resp_hex = fins_payload.hex().upper()
            normalized = '00' + resp_hex[:6] + ADDRESS_BYTES + resp_hex[20:]
            return normalized
        except (socket.error, socket.timeout) as e:
            logger.error('TCP FINS receive error: %s', e)
            self.close()
            return None

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None


class SimulatedFinsConnection(object):
    """Simulator PLC Omron lokal (In-Memory) yang kompatibel penuh dengan class FINS.
    Mendukung pembacaan & penulisan bit/word (termasuk W0.00, W0.01, dan CIO 100.00)
    serta simulasi rangkaian Self-Holding / Interlock:
      - Saat W0.00 = 1 -> Output 100.00 menyala (1)
      - Saat W0.01 = 1 -> Output 100.00 mati (0)
    """

    def __init__(self, auto_ladder=True):
        self.auto_ladder = auto_ladder
        self.bits = {}   # Key: (area_code, word, bit) -> 0 atau 1
        self.words = {}  # Key: (area_code, word) -> int (0..65535)
        self._last_response = None

    def _run_ladder_scan(self):
        if not self.auto_ladder:
            return
        w0_00 = self.bits.get((WR_BIT, 0, 0), 0)
        w0_01 = self.bits.get((WR_BIT, 0, 1), 0)
        out_100_00 = self.bits.get((CIO_BIT, 100, 0), 0)

        # Rangkaian Self-Holding Ladder Omron:
        # LD W0.00 OR 100.00 ANDNOT W0.01 OUT 100.00
        if w0_01 == 1:
            out_100_00 = 0
        elif w0_00 == 1:
            out_100_00 = 1
        self.bits[(CIO_BIT, 100, 0)] = out_100_00

    def send(self, fins_command):
        # Format fins_command:
        # [0:21]  = FINS_HEADER ('080000200000000000000')
        # [21:25] = command_code ('0101' atau '0102')
        # [25:]   = command_text
        cmd = fins_command[21:25]
        body = fins_command[25:]
        resp_prefix = '00' + ICF_RESPONSE + '0002' + ADDRESS_BYTES + cmd + '0000'

        if cmd == MEMORY_AREA_READ:
            area = body[0:2]
            word_addr = int(body[2:6], 16)
            bit_addr = int(body[6:8], 16)
            num_items = int(body[8:12], 16)
            item_size = ITEM_BYTE_SIZE.get(area, 1)

            self._run_ladder_scan()
            out_hex = []
            for i in range(num_items):
                if item_size == 1:
                    b_offset = bit_addr + i
                    w_actual = word_addr + (b_offset // 16)
                    b_actual = b_offset % 16
                    val = self.bits.get((area, w_actual, b_actual), 0)
                    out_hex.append(hex_string(val, 1))
                else:
                    val = self.words.get((area, word_addr + i), 0)
                    out_hex.append(hex_string(val, 2))
            self._last_response = resp_prefix + ''.join(out_hex)
            return True

        elif cmd == MEMORY_AREA_WRITE:
            area = body[0:2]
            word_addr = int(body[2:6], 16)
            bit_addr = int(body[6:8], 16)
            num_items = int(body[8:12], 16)
            data_hex = body[12:]
            item_size = ITEM_BYTE_SIZE.get(area, 1)
            char_len = item_size * 2

            for i in range(num_items):
                chunk = data_hex[i * char_len:(i + 1) * char_len]
                val = int(chunk, 16) if chunk else 0
                if item_size == 1:
                    b_offset = bit_addr + i
                    w_actual = word_addr + (b_offset // 16)
                    b_actual = b_offset % 16
                    self.bits[(area, w_actual, b_actual)] = 1 if val else 0
                else:
                    self.words[(area, word_addr + i)] = val & 0xFFFF

            self._run_ladder_scan()
            self._last_response = resp_prefix
            return True

        self._last_response = resp_prefix
        return True

    def receive(self):
        return self._last_response

    def close(self):
        pass


def hex_string(number, bytes=1):
    """Return a number converted to its hexadecimal string representation. It
    will be padded to the specified number of bytes. One byte is two characters.
    e.g. hex_string(1) returns '01'
         hex_string(10, 2) returns '000A'
    """
    return '{:0{width}X}'.format(number, width=bytes * 2)


def calculate_fcs(string):
    """Return the string representation of an FCS (frame check sequence)
    computed for the given `string`.
    """
    fcs = reduce(xor, (ord(c) for c in string))
    return hex_string(fcs)


def create_hostlink_command(data, device_id='00', header_code='FA'):
    """Return a Host Link command, encapsulating `data` (hexadecimal ASCII
    characters).

    `device_id` defaults to '00'; it represents the controller's ID.
    `header_code` defaults to 'FA' and distinguishes different types of Host
    Link commands.
    """
    header = '@' + device_id + header_code
    fcs = calculate_fcs(header + data)
    return header + data + fcs + '*\r'


def strip_hostlink_response(response, device_id='00', header_code='FA'):
    """Strip Host Link header and footer from response. Set `device_id` and
    `header_code` according to the Host Link command originally sent.

    Return data if everything checks out."""
    match = re.search(r"""@
                          {device_id}
                          {header_code}
                          (.*)   # Data
                          (\w\w) # FCS
                          \*\r   # Terminator
                      """.format(device_id=device_id, header_code=header_code),
                      response, re.VERBOSE)
    if match is not None:
        data, response_fcs = match.groups()
        hostlink_response = match.group(0)
        if calculate_fcs(hostlink_response[:-4]) == response_fcs:
            return data


def strip_fins_response(response, command_code):
    """Strip FINS header off the response and check that the command code and
    end code is valid.

    Return FINS text. An empty string ('') will be returned if there is no text.
    """
    match = re.match(r"""00
                         {icf}
                         \w{{4}}         # Ignore RSV and GCT.
                         {address_bytes}
                         {command_code}
                         0000            # End code
                         (\w*)           # Data
                     """.format(icf=ICF_RESPONSE, address_bytes=ADDRESS_BYTES,
                                command_code=command_code),
                     response, re.VERBOSE)
    if match is not None:
        (text,) = match.groups()
        return text
