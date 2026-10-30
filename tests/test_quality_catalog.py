from simpeople.core.quality_catalog import QualityCatalog,hash_tree,template_hash,SCHEMA

def test_catalog_invalidates_changed_asset_action_or_chair():
    record={'asset_revision_sha256':'asset','motion_revision_sha256':'motion','rig_id':'rig','kind':'seat','seat_template_sha256':'profile','seat_geometry_sha256':'geometry','status':'verified_vertex_audit'}
    c=QualityCatalog({'schema_version':SCHEMA,'records':[record]})
    assert c.query('asset','motion','rig','seat','profile','geometry')['revision_match']
    for args in [('changed','motion','rig','seat','profile','geometry'),('asset','changed','rig','seat','profile','geometry'),('asset','motion','rig','seat','changed','geometry'),('asset','motion','rig','seat','profile','changed')]:
        assert not c.query(*args)['revision_match']

def test_revision_includes_usd_dependencies_and_is_relocatable(tmp_path):
    one=tmp_path/'one';two=tmp_path/'two';one.mkdir();two.mkdir()
    for root in (one,two):
        (root/'person.usd').write_text('reference mesh.usda');(root/'mesh.usda').write_text('old shape')
    assert hash_tree(one)==hash_tree(two)
    (two/'mesh.usda').write_text('new shape');assert hash_tree(one)!=hash_tree(two)
    p={'position_m':[0,0,0],'yaw_rad':0,'hips_offset_m':[0,-.08,.56]};q={**p,'position_m':[8,9,0],'yaw_rad':1}
    assert template_hash(p)==template_hash(q)
    q['hips_offset_m']=[0,0,.56];assert template_hash(p)!=template_hash(q)

def test_quality_claim_is_specific_to_native_runtime_revision():
    row={'asset_revision_sha256':'a','motion_revision_sha256':'m','rig_id':'r','kind':'locomotion','runtime_revision':{'isaac':'reference'},'status':'measured_contact_proxy'}
    c=QualityCatalog({'schema_version':SCHEMA,'records':[row]})
    assert c.query('a','m','r','locomotion',runtime_revision={'isaac':'reference'})['revision_match']
    assert not c.query('a','m','r','locomotion',runtime_revision={'isaac':'newer'})['revision_match']
