import os, tempfile, copy, json, pytest
from types import SimpleNamespace
from capsula.evidence.proof import Signer, Vault, tree, inclusion, check_inclusion, canon, sha, unb64
from capsula.security.policy import evaluate, CAPABILITIES

@pytest.fixture
def signer(tmp_path):return Signer(tmp_path/'sign.pem')
@pytest.fixture
def vault(tmp_path):return Vault(tmp_path/'key')

def test_signatures_roundtrip(signer):
    p={'job':'abc','result':True};sig=signer.sign(p)
    assert signer.verify(p,sig)
    assert Signer.verify_external(p,sig,signer.public()['public_key'])
    assert Signer(signer.path).key_id==signer.key_id
    assert not signer.verify({'job':'abc','result':False},sig)
    assert not signer.verify(p,'broken')

def test_vault(vault):
    item={'secret':'data','ordinal':3};sealed=vault.seal(item,'task-1')
    assert vault.open(sealed,'task-1')==item
    with pytest.raises(Exception):vault.open(sealed,'task-2')
    with pytest.raises(Exception):vault.open({**sealed,'ciphertext':sealed['ciphertext'][:-2]+'ZZ'},'task-1')
    assert Vault(vault.path).open(sealed,'task-1')==item

def test_permissions(tmp_path):
    p=tmp_path/'bad.pem';p.write_text('x');os.chmod(p,0o644)
    with pytest.raises(RuntimeError,match='0600'):Signer(p)

def test_merkle_empty(): assert len(tree([]))==64

@pytest.mark.parametrize('size',[1,2,3,4,5,6,7,8,9,15,16,17,32,33,64,65])
def test_inclusion_matrix(size):
    items=[{'i':i,'detail':'event-'+str(i)} for i in range(size)]
    root=tree(items)
    assert len(root)==64
    for i in range(size):
        path=inclusion(items,i)
        assert check_inclusion(items[i],path,root)
        assert not check_inclusion({'i':-1},path,root)
        if i+1<size:assert not check_inclusion(items[i+1],path,root)
    with pytest.raises(IndexError):inclusion(items,size)

@pytest.mark.parametrize('kind',['browser','research','loom','pocket-agent','wallet','payments'])
def test_disabled_capabilities(kind):
    p=evaluate(SimpleNamespace(kind=kind,code='anything'),True)
    assert p['decision']=='deny'
    assert p['authority']['financial_spend'] is False
    assert p['authority']['subagents']==0

@pytest.mark.parametrize('code',['',' ','\n'])
def test_blank_python_denied(code):
    assert evaluate(SimpleNamespace(kind='python',code=code),True)['decision']=='deny'

def test_runtime_gate():
    assert evaluate(SimpleNamespace(kind='python',code='print(1)'),False)['decision']=='deny'
    assert evaluate(SimpleNamespace(kind='python',code='print(1)'),True)['decision']=='permit'
    assert evaluate(SimpleNamespace(kind='python',code='print(1)'),True)['limits']['network']=='none'

def test_unknown_capability():assert evaluate(SimpleNamespace(kind='shell',code='ls'),True)['decision']=='deny'

def test_signed_receipt_mutations(signer):
    payload={'a':1,'nested':{'x':3},'status':'denied'}
    sig=signer.sign(payload)
    assert signer.verify(payload,sig)
    for mutated in [{'a':2,'nested':{'x':3},'status':'denied'}, {'a':1,'nested':{'x':4},'status':'denied'}, {'a':1,'nested':{'x':3},'status':'permit'}]:
        assert not signer.verify(mutated,sig)
    assert not Signer.verify_external(payload,sig,Signer(tempfile.mkdtemp()+'/other.pem').public()['public_key'])

@pytest.mark.parametrize('payload',[{},[],['a'],{'a':1}, {'unicode':'ñ 🛰'}, {'zero':0,'none':None,'bool':False}])
def test_canonical_payloads(payload,signer):
    assert signer.verify(payload,signer.sign(payload))
    assert isinstance(canon(payload),bytes)
