"""CAPSULA Proof Protocol v2: durable Ed25519 identity, signed receipts and inclusion proofs.

Signatures establish provenance *from the configured installation key*, not the honesty
of a host or proof that Docker isolation occurred. Docker attestation remains separate.
"""
import os, json, hashlib, base64, pathlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature

DOMAIN=b'CAPSULA-PROOF-V2\x00'
EMPTY=hashlib.sha256(b'CAPSULA-EMPTY-V2').digest()

def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(v): return hashlib.sha256(v).hexdigest()
def b64(v): return base64.urlsafe_b64encode(v).decode().rstrip('=')
def unb64(v): return base64.urlsafe_b64decode(v+'='*((-len(v))%4))
def leaf(v): return hashlib.sha256(b'\x00'+v).digest()
def join(a,b): return hashlib.sha256(b'\x01'+a+b).digest()
def tree(leaves):
    nodes=[leaf(canon(i)) for i in leaves]
    if not nodes:return EMPTY.hex()
    while len(nodes)>1:
        nodes=[join(nodes[i],nodes[i+1] if i+1<len(nodes) else nodes[i]) for i in range(0,len(nodes),2)]
    return nodes[0].hex()
def inclusion(leaves,index):
    if index<0 or index>=len(leaves):raise IndexError('Missing leaf')
    nodes=[leaf(canon(x)) for x in leaves]; path=[];i=index
    while len(nodes)>1:
        j=i^1; path.append({'position':'right' if i%2==0 else 'left','hash':(nodes[j] if j<len(nodes) else nodes[i]).hex()})
        nodes=[join(nodes[k],nodes[k+1] if k+1<len(nodes) else nodes[k]) for k in range(0,len(nodes),2)];i//=2
    return path
def check_inclusion(item,path,root):
    node=leaf(canon(item))
    for p in path:
        sibling=bytes.fromhex(p['hash']);node=join(node,sibling) if p['position']=='right' else join(sibling,node)
    return node.hex()==root

class Signer:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists():
            if self.path.stat().st_mode&0o077:raise RuntimeError('Signing key must have mode 0600')
            self.private=serialization.load_pem_private_key(self.path.read_bytes(),password=None)
        else:
            self.private=Ed25519PrivateKey.generate()
            pem=self.private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            fd=os.open(str(self.path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(pem)
        self.pub=self.private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.key_id='ed25519:'+sha(self.pub)[:24]
    def sign(self,payload):return b64(self.private.sign(DOMAIN+canon(payload)))
    def verify(self,payload,signature):
        try:self.private.public_key().verify(unb64(signature),DOMAIN+canon(payload));return True
        except (InvalidSignature,ValueError):return False
    @staticmethod
    def verify_external(payload,signature,public_key):
        try:Ed25519PublicKey.from_public_bytes(unb64(public_key)).verify(unb64(signature),DOMAIN+canon(payload));return True
        except (InvalidSignature,ValueError):return False
    def public(self):return {'algorithm':'Ed25519','key_id':self.key_id,'public_key':b64(self.pub),'domain':'CAPSULA-PROOF-V2'}

class Vault:
    """AES-GCM encryption for selected sensitive records; never placed in the UI."""
    def __init__(self,path):
        self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists():
            if self.path.stat().st_mode&0o077:raise RuntimeError('Vault key must have mode 0600')
            self.key=self.path.read_bytes()
        else:
            self.key=AESGCM.generate_key(bit_length=256)
            fd=os.open(str(self.path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(self.key)
        if len(self.key)!=32:raise ValueError('Invalid vault key')
    def seal(self,data,context):
        nonce=os.urandom(12);return {'cipher':'AES-256-GCM','nonce':b64(nonce),'ciphertext':b64(AESGCM(self.key).encrypt(nonce,canon(data),context.encode()))}
    def open(self,blob,context):
        return json.loads(AESGCM(self.key).decrypt(unb64(blob['nonce']),unb64(blob['ciphertext']),context.encode()))
