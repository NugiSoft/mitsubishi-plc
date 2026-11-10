from datetime import datetime
import socket
import unittest

from unittest.mock import MagicMock, patch

import fins
from fins import FINS, TCPHostLinkConnection
from fins import calculate_fcs, create_hostlink_command, \
    hex_string, strip_fins_response, strip_hostlink_response


class FinsTestCase(unittest.TestCase):

    def test_hex_string(self):
        self.assertEqual(hex_string(1), '01')
        self.assertEqual(hex_string(10), '0A')
        self.assertEqual(hex_string(0xB2), 'B2')
        self.assertEqual(hex_string(0xB2, 2), '00B2')

    def test_calculate_fcs(self):
        self.assertEqual(calculate_fcs('@00XZ'), '42')
        self.assertEqual(
            calculate_fcs('@00FA08000020000000000000001018203E8000080'), '01')
        self.assertEqual(
            calculate_fcs('@00FA0800002000000000000000101B20000000001'), '0C')
        self.assertEqual(
            calculate_fcs('@00FA00C0000200000000000000010100000001'), '37')
        self.assertEqual(
            calculate_fcs('@00FA0800002000000000000000101B20031000001'), '0E')
        self.assertEqual(
            calculate_fcs('@00FA0800002000000000000000101B2002C000001'), '7D')
        self.assertEqual(
            calculate_fcs('@00FA00C0000200000000000000010100000000'), '36')
        self.assertEqual(
            calculate_fcs('@00FA0800002000000000000000101B20047000001'), '0F')
        self.assertEqual(
            calculate_fcs('@00FA00C0000200000000000000010100000503'), '30')

    def test_create_hostlink_command(self):
        self.assertEqual(
            '@04RIAL52*\r',
             create_hostlink_command('AL', device_id='04', header_code='RI'))
        self.assertEqual(
             '@00FA00C000020000000000000001010000200733*\r',
             create_hostlink_command('00C0000200000000000000010100002007'))

    def test_strip_hostlink_response(self):
        self.assertEqual(
            '00C0000200000000000000010100002007',
            strip_hostlink_response(
                '@00FA00C000020000000000000001010000200733*\r'))
        self.assertEqual(
            '00C0000200000000000000010100002037',
            strip_hostlink_response(
                '@00FA00C000020000000000000001010000203730*\r'))
        self.assertEqual(
            '00C0000200000000000000010100002037',
            strip_hostlink_response(
                'XXX@00FA00C000020000000000000001010000203730*\r'))
        self.assertEqual(
            '00C0000200000000000000010100002037',
            strip_hostlink_response(
                '@00FA00C000020000000000000001010000203730*\rXXX'))
        self.assertEqual(
            '00C0000200000000000000010100002037',
            strip_hostlink_response(
                'XXX@00FA00C000020000000000000001010000203730*\rXXX'))
        # FCS error
        self.assertIsNone(
            strip_hostlink_response(
                '@00FA00C000020000000100000001010000203730*\r'))

    def test_strip_fins_response(self):
        self.assertEqual(
            '2007',
            strip_fins_response('00C0000200000000000000010100002007', '0101'))
        self.assertEqual(
            '0503',
            strip_fins_response('00C0010000000000000000010100000503', '0101'))
        self.assertEqual(
            '',
            strip_fins_response('00C000020000000000000001010000', '0101'))
        self.assertIsNone(
            strip_fins_response('00C00002000000000000000101000', '0101'))
        self.assertIsNone(
            strip_fins_response('008000020000000000000001010000', '0101'))
        self.assertIsNone(
            strip_fins_response('00C000020000000000000001010000', '0102'))

    @patch('fins.strip_hostlink_response', return_value='fins')
    @patch('fins.create_hostlink_command', return_value='hostlink')
    @patch('fins.socket.create_connection')
    def test_TCPHostLinkConnection(
            self, mock_create_connection, mock_create_hostlink_command,
            mock_strip_hostlink_response):
        # Test invalid hosts and ports.
        mock_create_connection.side_effect = socket.gaierror()
        connection = TCPHostLinkConnection('localhost', 1)
        self.assertIsNone(connection.send('data'))
        mock_create_connection.assert_called_with(('localhost', 1), 2)

        # Test sending of data.
        mock_create_connection.side_effect = None
        self.assertTrue(connection.send('data'))
        mock_create_hostlink_command.assert_called_with('data')
        connection.socket.sendall.assert_called_with('hostlink')

        # Test socket error.
        mock_socket = MagicMock()
        mock_socket.sendall.side_effect = socket.error()
        connection.socket = mock_socket
        self.assertIsNone(connection.send('data'))
        self.assertIsNone(connection.socket)
        mock_socket.close.assert_called_with()

        # Test timeout error.
        mock_socket.sendall.side_effect = socket.timeout()
        connection.socket = mock_socket
        self.assertIsNone(connection.send('data'))
        self.assertIsNone(connection.socket)
        mock_socket.close.assert_called_with()

        # Test receive.
        mock_socket.recv.side_effect = ['test', 'stream*\r']
        connection.socket = mock_socket
        self.assertEqual('fins', connection.receive())
        self.assertIsNotNone(connection.socket)
        mock_strip_hostlink_response.assert_called_with('teststream*\r')

        mock_socket.recv.side_effect = ['test' 'stream*\r', 'more']
        connection.socket = mock_socket
        self.assertEqual('fins', connection.receive())
        self.assertIsNotNone(connection.socket)
        mock_strip_hostlink_response.assert_called_with('teststream*\r')

        mock_socket.recv.side_effect = ['test' 'str*\ream', 'more']
        connection.socket = mock_socket
        self.assertEqual('fins', connection.receive())
        self.assertIsNotNone(connection.socket)
        mock_strip_hostlink_response.assert_called_with('teststr*\ream')

        # Test receive errors.
        mock_socket.recv.side_effect = ['socket', 'closing', '']
        connection.socket = mock_socket
        self.assertIsNone(connection.receive())
        mock_socket.close.assert_called_with()
        self.assertIsNone(connection.socket)

        mock_socket.recv.side_effect = ['data', socket.error()]
        connection.socket = mock_socket
        self.assertIsNone(connection.receive())
        mock_socket.close.assert_called_with()
        self.assertIsNone(connection.socket)

        mock_socket.recv.side_effect = ['data', socket.timeout()]
        connection.socket = mock_socket
        self.assertIsNone(connection.receive())
        mock_socket.close.assert_called_with()
        self.assertIsNone(connection.socket)

    @patch('fins.strip_fins_response')
    def test_FINS_send(self, mock_strip_fins_response):
        connection = MagicMock()
        fins = FINS(connection)
        connection.receive.return_value = 'response'
        mock_strip_fins_response.return_value = 'text'

        # Test sending.
        self.assertEqual('text', fins.send('FF', '0123'))
        connection.send.assert_called_once_with('080000200000000000000FF0123')
        connection.receive.assert_called_once_with()
        mock_strip_fins_response.assert_called_once_with('response', 'FF')

        # Test unstrippable FINS response.
        connection.send.reset_mock()
        connection.receive.reset_mock()
        mock_strip_fins_response.reset_mock()
        mock_strip_fins_response.return_value = None
        self.assertIsNone(fins.send('FF', '0123'))
        connection.send.assert_called_with('080000200000000000000FF0123')
        connection.receive.assert_called_with()
        mock_strip_fins_response.assert_called_with('response', 'FF')
        self.assertEqual(3, connection.send.call_count)
        self.assertEqual(3, connection.receive.call_count)
        self.assertEqual(3, mock_strip_fins_response.call_count)

        # Test no response received.
        connection.send.reset_mock()
        connection.receive.reset_mock()
        mock_strip_fins_response.reset_mock()
        connection.receive.return_value = None
        self.assertIsNone(fins.send('FF', '0123'))
        connection.send.assert_called_with('080000200000000000000FF0123')
        connection.receive.assert_called_with()
        self.assertEqual(3, connection.send.call_count)
        self.assertEqual(3, connection.receive.call_count)
        self.assertEqual(0, mock_strip_fins_response.call_count)

        # Test can't send.
        connection.send.reset_mock()
        connection.receive.reset_mock()
        mock_strip_fins_response.reset_mock()
        connection.send.return_value = None
        self.assertIsNone(fins.send('FF', '0123'))
        connection.send.assert_called_with('080000200000000000000FF0123')
        self.assertEqual(3, connection.send.call_count)
        self.assertEqual(0, connection.receive.call_count)
        self.assertEqual(0, mock_strip_fins_response.call_count)

    def test_FINS_memory_area_read(self):
        fins = FINS(None)
        mock_send = MagicMock()
        fins.send = mock_send

        # Test send is called with correct parameters.
        mock_send.return_value = None
        self.assertIsNone(fins.memory_area_read('B2', 0xBEEF))
        mock_send.assert_called_with('0101', 'B2BEEF000001')
        self.assertIsNone(fins.memory_area_read('32', 0xBEEF, 3, num_items=2))
        mock_send.assert_called_with('0101', '32BEEF030002')
        fins.memory_area_read('B2', 0xBEEF, num_items=0)
        mock_send.assert_called_with('0101', 'B2BEEF000000')

        # Test correct parsing of values from response text.
        mock_send.return_value = 'BEEF'
        self.assertEqual([0xBEEF], fins.memory_area_read('B2', 0))
        mock_send.return_value = 'DEADBEEF'
        self.assertEqual([0xDEAD, 0xBEEF],
                         fins.memory_area_read('B2', 0, num_items=2))

        # Test that None is returned for more values returned than requested.
        self.assertIsNone(fins.memory_area_read('B2', 0))

        # Test bit values
        mock_send.return_value = '000100000101'
        self.assertEqual([0, 1, 0, 0, 1, 1],
                         fins.memory_area_read('32', 0, num_items=6))

        # Test BCD.
        mock_send.return_value = '23456789'
        self.assertEqual(
            [2345, 6789], fins.memory_area_read('B2', 0, num_items=2, bcd=True))

        # Test values in the wrong base. Should be set to 0.
        mock_send.return_value = '0001' '0002' '000F' '0004'
        self.assertEqual(
            [1, 2, 0, 4], fins.memory_area_read('B2', 0, num_items=4, bcd=True))

    def test_FINS_memory_area_read_single(self):
        fins = FINS(None)
        mock_send = MagicMock()
        fins.send = mock_send

        mock_send.return_value = None
        self.assertIsNone(fins.memory_area_read_single('B2', 0xBEEF))
        mock_send.assert_called_with('0101', 'B2BEEF000001')

        mock_send.return_value = 'BEEF'
        self.assertEqual(0xBEEF, fins.memory_area_read_single('B2', 0))

        # Test bit values
        mock_send.return_value = '01'
        self.assertEqual(1, fins.memory_area_read_single('32', 0))

        # Test BCD.
        mock_send.return_value = '1234'
        self.assertEqual(
            1234, fins.memory_area_read_single('B2', 0, bcd=True))

    def test_FINS_memory_area_write(self):
        fins = FINS(None)
        mock_send = MagicMock()
        fins.send = mock_send

        # Test writeing no values.
        fins.memory_area_write('B2', 0xFACE)
        mock_send.assert_called_with('0102', 'B2FACE000000')

        # Test writing single value.
        fins.memory_area_write('B2', 0xBEEF, 0, 0xFACE)
        mock_send.assert_called_with('0102', 'B2BEEF000001FACE')

        # Test writing multiple values.
        fins.memory_area_write('B2', 0, values=[0xDEAD, 0xBEEF, 0xFACE])
        mock_send.assert_called_with('0102', 'B20000000003DEADBEEFFACE')
        fins.memory_area_write('32', 0, 2, (1, 0, 1, 0, 1, 1, 0, 1))
        mock_send.assert_called_with('0102', '3200000200080100010001010001')

        # Test unable to send.
        mock_send.return_value = None
        self.assertIsNone(fins.memory_area_write('B2', 0xBEEF, 0, 0xFACE))

    def test_FINS_clock_read(self):
        fins = FINS(None)
        mock_send = MagicMock()
        fins.send = mock_send

        # Test correct command code is used.
        mock_send.return_value = None
        self.assertIsNone(fins.clock_read())
        mock_send.assert_called_with('0701')

        # Test response parsing.
        mock_send.return_value = '12040112345600'
        self.assertEqual(datetime(2012, 4, 1, 12, 34, 56), fins.clock_read())

        # Test bad date.
        mock_send.return_value = '12043212345600'
        self.assertIsNone(fins.clock_read())

    def test_FINS_clock_write(self):
        fins = FINS(None)
        mock_send = MagicMock()
        fins.send = mock_send

        # Test that send is called correctly.
        fins.clock_write(datetime(2012, 4, 1, 12, 34, 56))
        mock_send.assert_called_with('0702', '120401123456')


if __name__ == '__main__':
    unittest.main()
