import socket
import threading

peers = []

def handle_client(client_socket, peers):
    while True:
        request = client_socket.recv(1024).decode()
        if not request:
            break
        
        command, *args = request.split()
        
        if command == "REGISTER":
            peer_info = f"{args[0]}:{args[1]}"
            if peer_info not in peers:
                peers.append(peer_info)
                client_socket.send(b"Registered successfully.")
            else: client_socket.send(b"You have already regidtered.")
        
        elif command == "GET_PEERS":
            peer_list = "\n".join(peers).encode()
            client_socket.send(peer_list)
        
        elif command == "UNREGISTER":
            peer_info = f"{args[0]}:{args[1]}"
            if peer_info in peers:
                peers.remove(peer_info)
                client_socket.send(b"Unregistered successfully.")
            else:
                client_socket.send(b"You were not registered.")

    
    client_socket.close()

def start_tracker(host='192.168.0.100', port=5000):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((host, port))
    server.listen(5)
    print(f"Tracker running on {host}:{port}")
    
    while True:
        client_sock, addr = server.accept()
        print(f"Connection from {addr}")
        client_handler = threading.Thread(target=handle_client, args=(client_sock,peers))
        client_handler.start()

if __name__ == '__main__':
    start_tracker()