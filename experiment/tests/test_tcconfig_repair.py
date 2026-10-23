"""Database/exit-status regressions; these are not packet measurements."""
import errno
import json
import unittest
from tcconfig._docker import DockerClient,IfIndex
from tcconfig._main import Main
from simplesqlite import connect_memdb


class NamespaceMapping(unittest.TestCase):
    def setUp(self):
        self.db=connect_memdb()
        IfIndex.attach(self.db)
        IfIndex.create()
        self.client=object.__new__(DockerClient)
        self.client._DockerClient__host_name='host:net:[123]'

    def tearDown(self):self.db.close()

    def add(self,namespace,index,name,peer):
        IfIndex.insert(IfIndex(record_key=json.dumps([namespace,index]),host=namespace,
            ifindex=index,ifname=name,peer_ifindex=peer))
        IfIndex.commit()

    def test_repeated_peer_indices_preserve_every_target(self):
        # Actual failure pattern: three host peers all refer to eth0/index2,
        # each in a different namespace. Reverse order must not alter mapping.
        for index in [14,13,10]:self.add('host:net:[123]',index,'veth'+str(index),2)
        self.add('cloud',2,'eth0',13)
        self.assertEqual(self.client.fetch_veth_list('cloud'),['veth13'])

    def test_same_local_index_in_host_and_container_is_legal(self):
        self.add('host:net:[123]',2,'veth2',2)
        self.add('cloud',2,'eth0',2)
        self.assertEqual(self.client.fetch_veth_list('cloud'),['veth2'])

    def test_multihomed_target_requires_both_reciprocal_peers(self):
        self.add('host:net:[123]',10,'veth10',2)
        self.add('host:net:[123]',11,'veth11',3)
        self.add('fog',2,'eth0',10)
        self.add('fog',3,'eth1',11)
        self.assertEqual(set(self.client.fetch_veth_list('fog')),{'veth10','veth11'})

    def test_missing_peer_fails(self):
        self.add('cloud',2,'eth0',13)
        with self.assertRaises(ValueError):self.client.fetch_veth_list('cloud')

    def test_nonreciprocal_peer_fails(self):
        self.add('host:net:[123]',13,'veth13',7)
        self.add('cloud',2,'eth0',13)
        with self.assertRaises(ValueError):self.client.fetch_veth_list('cloud')

    def test_empty_namespace_fails(self):
        with self.assertRaises(ValueError):self.client.fetch_veth_list('cloud')


class ExitStatus(unittest.TestCase):
    def test_empty_and_partial_failures_remain_failures(self):
        main=object.__new__(Main)
        self.assertEqual(main._get_return_code([]),errno.ENODEV)
        self.assertEqual(main._get_return_code([0,7]),7)
        self.assertEqual(main._get_return_code([7,0]),7)
        self.assertEqual(main._get_return_code([0,0]),0)


if __name__=='__main__':unittest.main(verbosity=2)
