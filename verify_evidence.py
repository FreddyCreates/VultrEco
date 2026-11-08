"""Verify an exported CAPSULA v2 evidence JSON against a pinned operator key.

Example: python verify_evidence.py evidence.json --public-key BASE64URL
This verifies data origin/integrity only; it does NOT attest host security.
"""
import argparse,json,sys
from proof import Signer, canon,tree,sha,unb64,check_inclusion

def verify(evidence,trust_pub):
    r=evidence['receipt'];p=r['payload'];events=evidence['events']
    if r['public_key']['public_key']!=trust_pub:return False
    if not Signer.verify_external(p,r['signature'],trust_pub):return False
    if p['protocol']!='capsula.proof.v2':return False
    if p['merkle_root']!=tree(events) or p['event_count']!=len(events):return False
    if p['event_chain_head']!=(events[-1]['hash'] if events else '0'*64):return False
    if p['result_digest']!=sha(canon(evidence['output'])):return False
    import hashlib
    prev='0'*64
    for event in events:
        canonical_event={'mission_id':p['mission_id'],'ts':event['ts'],'type':event['type'],'payload':event['payload'],'prev_hash':prev}
        if event['prev_hash']!=prev or event['hash']!=hashlib.sha256(canon(canonical_event)).hexdigest():return False
        prev=event['hash']
    inc=evidence.get('inclusion')
    if inc and not check_inclusion(events[inc['index']],inc['path'],p['merkle_root']):return False
    return True

def main():
    parser=argparse.ArgumentParser();parser.add_argument('file');parser.add_argument('--public-key',required=True,help='Previously trusted base64url Ed25519 public key')
    a=parser.parse_args()
    try:valid=verify(json.load(open(a.file,encoding='utf-8')),a.public_key)
    except (ValueError,KeyError,IndexError,TypeError) as e:valid=False
    print(json.dumps({'evidence_valid':valid,'trust':'operator-key-pinned','sandbox_attestation':'not-verified'}))
    return 0 if valid else 1
if __name__=='__main__':sys.exit(main())
