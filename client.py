import socket
import threading
import time
import bencodepy 
import os
import sys
import hashlib
import logging
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

# Set up logging
# logging.basicConfig(filename='log.txt', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BUFFER_SIZE = 2 * 4096
MAX_THREADS = 5

#lock
hash_dict_lock = threading.Lock()
file_lock = threading.Lock()
downloaded_lock = threading.Lock()
queue_lock = threading.Lock()

#Global
pieces_downloaded = 0 
HASH_DICT = {} 
PIECE_QUEUE = queue.Queue()

# Read info from metainfo.torrent
def read_torrent_file(torrent_file_path):
    try:
        if not os.path.exists(torrent_file_path):
            print(f"File {torrent_file_path} not found.")
            sys.exit()

        with open(torrent_file_path, 'rb') as torrent_file:
            torrent_data = bencodepy.decode(torrent_file.read())

        tracker_URL = torrent_data.get(b'announce', b'').decode()  # x.x.x.x:y
        info = torrent_data.get(b'info')
        file_name = info.get(b'name')
        piece_length = info.get(b'piece length', 0)  # 512KB
        pieces = info.get(b'pieces')  # list hash       
        file_length = info.get(b'length')
        pieces_count = len(pieces)
        # default bitfield 0 indicate client has not had this piece 
        hash_dict = {piece_hash.decode(): 0 for piece_hash in pieces.keys()} 
    except Exception as e:
        print(f"Error when dealing with torrent file: {e}")
    return hash_dict, tracker_URL, file_name, piece_length, piece_length, pieces, file_length, pieces_count        

def register_peer(tracker_URL, client_ip, client_port):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((tracker_URL.split(':')[0], int(tracker_URL.split(':')[1])))
        client.send(f"REGISTER {client_ip} {client_port}".encode())
        response = client.recv(4096).decode()
    except Exception as e:
        print(f"Error registering peer: {e}")
        return None
    finally:
        client.close()
    return response

def get_peers(tracker_URL):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((tracker_URL.split(':')[0], int(tracker_URL.split(':')[1])))
        client.send(b"GET_PEERS")
        response = client.recv(4096).decode()
    except Exception as e:
        print(f"Error getting peers: {e}")
        return []
    finally:
        client.close()
    return response.splitlines()

def unregister(tracker_URL, client_ip, client_port):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((tracker_URL.split(':')[0], int(tracker_URL.split(':')[1])))
        client.send(f"UNREGISTER {client_ip} {client_port}".encode())
        response = client.recv(4096).decode()
    except Exception as e:
        print(f"Error unregistering peer: {e}")
    finally:
        client.close()

def handle_leecher(client_socket):
    try:
        while True:
            request = client_socket.recv(BUFFER_SIZE).decode()
            if not request:
                break
            if request.startswith("REQUEST_HASH_LIST"):
                client_socket.send(str(list(HASH_DICT.keys())).encode())
            elif request.startswith("SEND_PIECE"):
                piece_hash = request.split()[1]
                piece_file_path = f'list_pieces/{piece_hash}.bin'
                try:
                    with open(piece_file_path, 'rb') as f:
                        total_sent = 0 
                        while True:
                            piece_data = f.read(BUFFER_SIZE)
                            if not piece_data:
                                break
                            total_sent += client_socket.send(piece_data)
                            signal = client_socket.recv(BUFFER_SIZE).decode()
                            if signal == "DONE":
                                continue
                            if signal == "ERROR":
                                raise Exception("Error message from leecher")
                    client_socket.send(b'END')
                    print(f"Sent {total_sent} bytes of piece {piece_hash} to {client_socket.getpeername()}")
                except FileNotFoundError:
                    print(f"Piece {piece_hash} not found.")
                    client_socket.send(b'ERROR')
                except Exception as e:
                    client_socket.send(b'ERROR')
                    print(f"An error occurred: {e}")
    finally:
        client_socket.close()

def this_client_is_listening(tracker_URL, client_ip, client_port):
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as listener:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((client_ip, client_port))
        server.listen(5)
        server.settimeout(10)
        print(f"Client {client_ip}:{client_port} is listening.")
        try:
            while True:
                try:
                    client_sock, addr = server.accept()
                    print(f"Connection from {addr}")
                    listener.submit(handle_leecher, client_sock)
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Error while accepting connection: {e}")
                    break
        finally:
            unregister(tracker_URL, client_ip, client_port)
            server.close()
            print(f"{client_ip}:{client_port} closed.")
        server.close()
        print(f"{client_ip}:{client_port} closed.")

def update_downloaded_count_and_print(pieces_count):
    global pieces_downloaded
    with downloaded_lock:
        pieces_downloaded += 1
        percent_completed = (pieces_downloaded / pieces_count) * 100
        print(f"Downloading... {percent_completed:.2f}%")

def request_data(seeder_ip, seeder_port, pieces_count):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((seeder_ip, seeder_port))
        client.send(b"REQUEST_HASH_LIST")
        hash_list = client.recv(4096).decode().strip("[]").replace("'", "").split(", ")
        print(f"Hash list from {seeder_ip}:{seeder_port}: {hash_list}")

        while True: 
            with queue_lock:
                if PIECE_QUEUE.empty():
                    break
                piece_hash = PIECE_QUEUE.get()

            with hash_dict_lock:
                if HASH_DICT.get(piece_hash) == 1:
                    continue
            
            if piece_hash in HASH_DICT:
                try:
                    client.send(f"SEND_PIECE {piece_hash}".encode())
                    piece_data = client.recv(BUFFER_SIZE)
                    if piece_data == b'ERROR':
                        print(f"Error requesting piece {piece_hash} from {seeder_ip}:{seeder_port}")
                        with queue_lock:
                            PIECE_QUEUE.put(piece_hash)
                        continue
                    #download
                    with open(f'list_pieces/{piece_hash}.bin', 'wb') as f:
                        while piece_data and piece_data != b'END':
                            f.write(piece_data)
                            client.send(b'DONE')
                            piece_data = client.recv(BUFFER_SIZE)
                    #check
                    with open(f'list_pieces/{piece_hash}.bin', 'rb') as f:
                        piece = f.read()
                        piece_hash_test = hashlib.sha1(piece).hexdigest()
                        if piece_hash_test == piece_hash:
                            print(f"Received piece {piece_hash} from {seeder_ip}:{seeder_port}")
                            with hash_dict_lock:
                                HASH_DICT[piece_hash] = 1
                            update_downloaded_count_and_print(pieces_count)
                        else:
                            print(f"Hash mismatch for piece {piece_hash}. Expected: {piece_hash}, but received: {piece_hash_test}")
                            os.remove(f'list_pieces/{piece_hash}.bin')
                            with queue_lock:
                                PIECE_QUEUE.put(piece_hash)
                except Exception as e:
                    print(f"Error during receive data for piece {piece_hash}: {e}")
                    if os.path.exists(f'list_pieces/{piece_hash}.bin'):
                        os.remove(f'list_pieces/{piece_hash}.bin')
                    with queue_lock:
                        PIECE_QUEUE.put(piece_hash)
    finally:
        client.close()

def algorithm(peer_list, this_IP, pieces_count):
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as run:
        for peer in peer_list:
            peer_info = peer.split(':')
            peer_ip = peer_info[0]
            peer_port = int(peer_info[1])
            if peer_ip != this_IP:
                run.submit(request_data, peer_ip, peer_port, pieces_count)

def run(tracker_URL, this_IP, pieces_count):
    used_list = []
    while True:
        new_peer_list = get_peers(tracker_URL)
        print("Updated Peers:")
        for peer in new_peer_list:
            print(peer)

        new_peers_to_request = [peer for peer in new_peer_list if peer not in used_list]
        used_list = new_peer_list.copy()      
        if new_peers_to_request:
            algorithm(new_peers_to_request, this_IP, pieces_count)
        time.sleep(5)
        with queue_lock:
            if PIECE_QUEUE.empty():
                print("Finish Downloading")
                break

def check_existing_pieces():
    global pieces_downloaded
    existing_pieces = os.listdir('list_pieces')
    for file in existing_pieces:
        if file.endswith('.bin'):
            piece_hash = file[:-4]
            HASH_DICT[piece_hash] = 1
            pieces_downloaded += 1


if __name__ == '__main__':
    THIS_IP = '0.0.0.0'
    THIS_PORT = 5000
    METAINFO_PATH = 'metainfo.torrent'

    HASH_DICT, tracker_URL, file_name, piece_length, piece_length, pieces, file_length, pieces_count = read_torrent_file(METAINFO_PATH)
    if not os.path.exists('list_pieces'):
        os.makedirs('list_pieces')
    check_existing_pieces()
    for piece_hash in HASH_DICT.keys():
        if HASH_DICT[piece_hash] == 0:
            PIECE_QUEUE.put(piece_hash)

    register_peer(tracker_URL, THIS_IP, THIS_PORT)

    threading.Thread(target=this_client_is_listening, args=(tracker_URL,THIS_IP, THIS_PORT)).start()
    
    peer_list = get_peers(tracker_URL)

    run(tracker_URL, THIS_IP, pieces_count)
