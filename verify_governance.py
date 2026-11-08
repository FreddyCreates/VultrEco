"""Offline governance chain verifier. Must pin the key from a trustworthy source."""
import json,argparse
from proof import Signer,canon,sha

def verify_bundle(data,public_key):
    prev='0'*64
    for row in data['entries']:
        statement={'protocol':'capsula.governance-evidence.v1','id':row['id'],'ts':row['ts'],'actor':row['actor'],'action':row['action'],'subject':row['subject'],'payload':json.loads(row['payload']) if isinstance(row['payload'],str) else row['payload'],'prev_hash':row['prev_hash']}
        if statement['prev_hash']!=prev or row['event_hash']!=sha(canon(statement)) or not Signer.verify_external(statement,row['signature'],public_key):return False
        prev=row['event_hash']
    return True

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('file');p.add_argument('--public-key',required=True)
    args=p.parse_args()
    with open(args.file,encoding='utf-8') as f:payload=json.load(f)
    good=verify_bundle(payload,args.public_key)
    print(json.dumps({'verified':good,'events':len(payload.get('entries',[])),'external_witness':False}))
    raise SystemExit(0 if good else 1)
