import os
import sys
import bencodepy

def read_torrent_file(torrent_file_path):
    if not os.path.exists(torrent_file_path):
        print(f"File {torrent_file_path} not found.")
        sys.sleep(5)
        sys.exit()

    with open(torrent_file_path, 'rb') as torrent_file:
        torrent_data = bencodepy.decode(torrent_file.read())

    info = torrent_data.get(b'info')
    if not info:
        print("Invalid torrent file format!!!")
        sys.sleep(5)
        sys.exit()

    pieces = info.get(b'pieces') #list hash
    if not pieces: 
        print("HASH value not found in torrent file!")
        sys.sleep(5)
        sys.exit()
    
    piece_length = info.get(b'piece length', 0) #512KB
    if not piece_length:
        print("PIECE LENGTH not found in torrent file!")
        sys.sleep(5)
        sys.exit()

    tracker_URL = torrent_data.get(b'announce', b'').decode() # x.x.x.x:y
    if not tracker_URL:
        print("TRACKER URL not found in torrent file!")
        sys.sleep(5)
        sys.exit()
    
    # default bitfield 0 indicate client has not had this piece 
    hash_dict = {piece_hash.decode(): 0 for piece_hash in pieces.keys()} 
    
    return hash_dict, piece_length, tracker_URL

def concatenate_files(hash_dict, output_file):
    with open(output_file, 'wb') as outfile:
        for piece_hash in hash_dict.keys():
            file_name = f"list_pieces/{piece_hash}.bin"
            if os.path.exists(file_name):
                with open(file_name, 'rb') as infile:
                    outfile.write(infile.read())
            else:
                print(f"File {file_name} không tồn tại.")
    print(f"Đã tạo file {output_file}.")

if __name__ == "__main__":
    torrent_file_path = 'metainfo.torrent'  # Đường dẫn đến file torrent
    hash_dict, piece_length, tracker_URL = read_torrent_file(torrent_file_path)

    if hash_dict:
        concatenate_files(hash_dict, "video_received.mp4")
