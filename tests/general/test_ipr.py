import os
import errno
import socket
from pyroute2 import IPRoute
from pyroute2.common import uifname
from pyroute2.common import AF_MPLS
from pyroute2.netlink import NetlinkError
from pyroute2.netlink import nlmsg
from pyroute2.netlink.rtnl.req import IPRouteRequest
from pyroute2.netlink.rtnl.ifinfmsg import ifinfmsg
from utils import grep
from utils import require_user
from utils import require_kernel
from utils import require_python
from utils import get_ip_brd
from utils import get_ip_addr
from utils import get_ip_link
from utils import get_ip_route
from utils import get_ip_default_routes
from utils import get_ip_rules
from utils import create_link
from utils import remove_link
from utils import skip_if_not_supported
from nose.plugins.skip import SkipTest


class TestSetup(object):

    def test_simple(self):
        ip = IPRoute()
        ip.close()

    def test_multiple_instances(self):
        ip1 = IPRoute()
        ip2 = IPRoute()
        ip1.close()
        ip2.close()

    def test_fileno_fail(self):
        require_python(2)
        try:
            IPRoute(fileno=13)
        except NotImplementedError:
            pass

    def test_fileno(self):
        require_python(3)
        ip1 = IPRoute()
        ip2 = IPRoute(fileno=ip1.fileno())

        ip2.bind()
        try:
            ip1.bind()
        except OSError as e:
            if e.errno != 22:  # bind -> Invalid argument
                raise

        ip1.close()
        try:
            ip2.get_links()
        except OSError as e:
            if e.errno != 9:   # sendto -> Bad file descriptor
                raise

        try:
            ip2.close()
        except OSError as e:
            if e.errno != 9:   # close -> Bad file descriptor
                raise


class TestMisc(object):

    def setup(self):
        self.ip = IPRoute()

    def teardown(self):
        self.ip.close()

    def test_get_policy_map(self):
        assert isinstance(self.ip.get_policy_map(), dict)

    def test_register_policy(self):
        self.ip.register_policy(100, nlmsg)
        self.ip.register_policy({101: nlmsg})
        self.ip.register_policy(102, nlmsg)

        assert self.ip.get_policy_map()[100] == nlmsg
        assert self.ip.get_policy_map(101)[101] == nlmsg
        assert self.ip.get_policy_map([102])[102] == nlmsg

        self.ip.unregister_policy(100)
        self.ip.unregister_policy([101])
        self.ip.unregister_policy({102: nlmsg})

        assert 100 not in self.ip.get_policy_map()
        assert 101 not in self.ip.get_policy_map()
        assert 102 not in self.ip.get_policy_map()

    def test_addrpool_expand(self):
        # see coverage
        for i in range(100):
            self.ip.get_addr()

    def test_nla_compare(self):
        lvalue = self.ip.get_links()
        rvalue = self.ip.get_links()
        assert lvalue is not rvalue
        if lvalue == rvalue:
            pass
        if lvalue != rvalue:
            pass
        assert lvalue != 42


def _callback(msg, obj):
    obj.cb_counter += 1


class TestIPRoute(object):

    def setup(self):
        self.ip = IPRoute()
        try:
            self.dev, idx = self.create()
            self.ifaces = [idx]
        except IndexError:
            pass

    def create(self, kind='dummy'):
        name = uifname()
        create_link(name, kind=kind)
        idx = self.ip.link_lookup(ifname=name)[0]
        return (name, idx)

    def teardown(self):
        if hasattr(self, 'ifaces'):
            for dev in self.ifaces:
                try:
                    self.ip.link('delete', index=dev)
                except:
                    pass
        self.ip.close()

    def _test_nla_operators(self):
        require_user('root')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.1', mask=24)
        self.ip.addr('add', self.ifaces[0], address='172.16.0.2', mask=24)
        r = [x for x in self.ip.get_addr() if x['index'] == self.ifaces[0]]
        complement = r[0] - r[1]
        intersection = r[0] & r[1]

        assert complement.get_attr('IFA_ADDRESS') == '172.16.0.1'
        assert complement.get_attr('IFA_LABEL') is None
        assert complement['prefixlen'] == 0
        assert complement['index'] == 0

        assert intersection.get_attr('IFA_ADDRESS') is None
        assert intersection.get_attr('IFA_LABEL') == self.dev
        assert intersection['prefixlen'] == 24
        assert intersection['index'] == self.ifaces[0]

    def test_addr_add(self):
        require_user('root')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.1', mask=24)
        assert '172.16.0.1/24' in get_ip_addr()

    def test_addr_broadcast(self):
        require_user('root')
        self.ip.addr('add', self.ifaces[0],
                     address='172.16.0.1',
                     mask=24,
                     broadcast='172.16.0.250')
        assert '172.16.0.250' in get_ip_brd()

    def test_addr_broadcast_default(self):
        require_user('root')
        self.ip.addr('add', self.ifaces[0],
                     address='172.16.0.1',
                     mask=24,
                     broadcast=True)
        assert '172.16.0.255' in get_ip_brd()

    def test_flush_addr(self):
        require_user('root')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.1', mask=24)
        self.ip.addr('add', self.ifaces[0], address='172.16.0.2', mask=24)
        self.ip.addr('add', self.ifaces[0], address='172.16.1.1', mask=24)
        self.ip.addr('add', self.ifaces[0], address='172.16.1.2', mask=24)
        assert len(self.ip.get_addr(index=self.ifaces[0],
                                    family=socket.AF_INET)) == 4
        self.ip.flush_addr(index=self.ifaces[0])
        assert len(self.ip.get_addr(index=self.ifaces[0],
                                    family=socket.AF_INET)) == 0

    def test_flush_rules(self):
        require_user('root')
        init = len(self.ip.get_rules(family=socket.AF_INET))
        assert len(self.ip.get_rules(priority=lambda x: 100 < x < 500)) == 0
        self.ip.rule('add', table=10, priority=110)
        self.ip.rule('add', table=15, priority=150, action='FR_ACT_PROHIBIT')
        self.ip.rule('add', table=20, priority=200, src='172.16.200.1')
        self.ip.rule('add', table=25, priority=250, dst='172.16.250.1')
        assert len(self.ip.get_rules(priority=lambda x: 100 < x < 500)) == 4
        assert len(self.ip.get_rules(src='172.16.200.1')) == 1
        assert len(self.ip.get_rules(dst='172.16.250.1')) == 1
        self.ip.flush_rules(family=socket.AF_INET,
                            priority=lambda x: 100 < x < 500)
        assert len(self.ip.get_rules(priority=lambda x: 100 < x < 500)) == 0
        assert len(self.ip.get_rules(src='172.16.200.1')) == 0
        assert len(self.ip.get_rules(dst='172.16.250.1')) == 0
        assert len(self.ip.get_rules(family=socket.AF_INET)) == init

    def test_rules_deprecated(self):
        require_user('root')
        init = len(self.ip.get_rules(family=socket.AF_INET))
        assert len(self.ip.get_rules(priority=lambda x: 100 < x < 500)) == 0
        self.ip.rule('add', 10, 110)
        self.ip.rule('add', 15, 150, 'FR_ACT_PROHIBIT')
        assert len(self.ip.get_rules(priority=lambda x: 100 < x < 500)) == 2
        self.ip.flush_rules(family=socket.AF_INET,
                            priority=lambda x: 100 < x < 500)
        assert len(self.ip.get_rules(priority=lambda x: 100 < x < 500)) == 0
        assert len(self.ip.get_rules(family=socket.AF_INET)) == init

    def test_addr_filter(self):
        require_user('root')
        self.ip.addr('add',
                     index=self.ifaces[0],
                     address='172.16.0.1',
                     prefixlen=24,
                     broadcast='172.16.0.255')
        self.ip.addr('add',
                     index=self.ifaces[0],
                     address='172.16.0.2',
                     prefixlen=24,
                     broadcast='172.16.0.255')
        assert len(self.ip.get_addr(index=self.ifaces[0])) == 2
        assert len(self.ip.get_addr(address='172.16.0.1')) == 1
        assert len(self.ip.get_addr(broadcast='172.16.0.255')) == 2
        assert len(self.ip.get_addr(match=lambda x: x['index'] ==
                                    self.ifaces[0])) == 2

    @skip_if_not_supported
    def _create_ipvlan(self, smode):
        master = uifname()
        ipvlan = uifname()
        # create the master link
        self.ip.link_create(ifname=master, kind='dummy')
        midx = self.ip.link_lookup(ifname=master)[0]
        # check modes
        # maybe move modes dict somewhere else?
        cmode = ifinfmsg.ifinfo.ipvlan_data.modes[smode]
        assert ifinfmsg.ifinfo.ipvlan_data.modes[cmode] == smode
        # create ipvlan
        self.ip.link_create(ifname=ipvlan,
                            kind='ipvlan',
                            link=midx,
                            mode=cmode)
        devs = self.ip.link_lookup(ifname=ipvlan)
        assert devs
        self.ifaces.extend(devs)

    def test_create_ipvlan_l2(self):
        return self._create_ipvlan('IPVLAN_MODE_L2')

    def test_create_ipvlan_l3(self):
        return self._create_ipvlan('IPVLAN_MODE_L3')

    @skip_if_not_supported
    def _create(self, kind):
        name = uifname()
        self.ip.link_create(ifname=name, kind=kind)
        devs = self.ip.link_lookup(ifname=name)
        assert devs
        self.ifaces.extend(devs)

    def test_create_dummy(self):
        require_user('root')
        self._create('dummy')

    def test_create_bond(self):
        require_user('root')
        self._create('bond')

    def test_create_bridge(self):
        require_user('root')
        self._create('bridge')

    def test_create_team(self):
        require_user('root')
        self._create('team')

    def test_ntables(self):
        setA = set(filter(lambda x: x is not None,
                          [x.get_attr('NDTA_PARMS').get_attr('NDTPA_IFINDEX')
                           for x in self.ip.get_ntables()]))
        setB = set([x['index'] for x in self.ip.get_links()])
        assert setA == setB

    def test_neigh_real_links(self):
        links = set([x['index'] for x in self.ip.get_links()])
        neigh = set([x['ifindex'] for x in self.ip.get_neighbours()])
        assert neigh < links

    def test_neigh_filter(self):
        require_user('root')
        # inject arp records
        self.ip.neigh('add',
                      dst='172.16.45.1',
                      lladdr='00:11:22:33:44:55',
                      ifindex=self.ifaces[0])
        self.ip.neigh('add',
                      dst='172.16.45.2',
                      lladdr='00:11:22:33:44:55',
                      ifindex=self.ifaces[0])
        # assert two arp records on the interface
        assert len(self.ip.get_neighbours(ifindex=self.ifaces[0])) == 2
        # filter by dst
        assert len(self.ip.get_neighbours(dst='172.16.45.1')) == 1
        # filter with lambda
        assert len(self.ip.get_neighbours(match=lambda x: x['ifindex'] ==
                                          self.ifaces[0])) == 2

    def test_mass_ipv6(self):
        #
        # Achtung! This test is time consuming.
        # It is really time consuming, I'm not not
        # kidding you. Beware.
        #
        require_user('root')
        base = 'fdb3:84e5:4ff4:55e4::{0}'
        limit = int(os.environ.get('PYROUTE2_SLIMIT', '0x800'), 16)

        # add addresses
        for idx in range(limit):
            self.ip.addr('add', self.ifaces[0],
                         base.format(hex(idx)[2:]), 48)

        # assert addresses in two steps, to ease debug
        addrs = self.ip.get_addr(10)
        assert len(addrs) >= limit

        # clean up addresses
        #
        # it is not required, but if you don't do that,
        # you'll get this on the interface removal:
        #
        # >> kernel:BUG: soft lockup - CPU#0 stuck for ...
        #
        # so, not to scare people, remove addresses gracefully
        # one by one
        #
        # it also verifies all the addresses are in place
        for idx in reversed(range(limit)):
            self.ip.addr('delete', self.ifaces[0],
                         base.format(hex(idx)[2:]), 48)

    def test_fail_not_permitted(self):
        try:
            self.ip.addr('add', 1, address='172.16.0.1', mask=24)
        except NetlinkError as e:
            if e.code != errno.EPERM:  # Operation not permitted
                raise
        finally:
            try:
                self.ip.addr('delete', 1, address='172.16.0.1', mask=24)
            except:
                pass

    def test_fail_no_such_device(self):
        require_user('root')
        dev = sorted([i['index'] for i in self.ip.get_links()])[-1] + 10
        try:
            self.ip.addr('add',
                         dev,
                         address='172.16.0.1',
                         mask=24)
        except NetlinkError as e:
            if e.code != errno.ENODEV:  # No such device
                raise

    def test_remove_link(self):
        require_user('root')
        try:
            self.ip.link_remove(self.ifaces[0])
        except NetlinkError:
            pass
        assert len(self.ip.link_lookup(ifname=self.dev)) == 0

    def test_route_oif_as_iterable(self):
        require_user('root')
        spec = {'dst': '172.16.0.0',
                'dst_len': 24,
                'oif': (1, )}
        self.ip.route('add', **spec)
        rts = self.ip.get_routes(family=socket.AF_INET,
                                 dst='172.16.0.0')
        self.ip.route('del', **spec)
        assert len(rts) == 1
        assert rts[0].get_attr('RTA_OIF') == 1

    def test_route_get_target(self):
        if not self.ip.get_default_routes(table=254):
            raise SkipTest('no default IPv4 routes')
        rts = self.ip.get_routes(family=socket.AF_INET,
                                 dst='8.8.8.8',
                                 table=254)
        assert len(rts) > 0

    def test_route_get_target_default_ipv4(self):
        rts = self.ip.get_routes(dst='127.0.0.1')
        assert len(rts) > 0

    def test_route_get_target_default_ipv6(self):
        rts = self.ip.get_routes(dst='::1')
        assert len(rts) > 0

    def test_route_get_by_spec(self):
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', index=self.ifaces[0],
                     address='172.16.60.1', mask=24)
        self.ip.addr('add', index=self.ifaces[0],
                     address='172.16.61.1', mask=24)
        rts = self.ip.get_routes(family=socket.AF_INET,
                                 dst=lambda x: x in ('172.16.60.0',
                                                     '172.16.61.0'))
        assert len(rts) == 4

    @skip_if_not_supported
    def _test_route_mpls_via_ipv(self, family, address, label):
        require_user('root')
        require_kernel(3)
        self.ip.route('add', **{'family': AF_MPLS,
                                'oif': self.ifaces[0],
                                'via': {'family': family,
                                        'addr': address},
                                'newdst': {'label': label,
                                           'bos': 1}})
        rt = self.ip.get_routes(oif=self.ifaces[0])[0]
        assert rt.get_attr('RTA_VIA')['addr'] == address
        assert rt.get_attr('RTA_VIA')['family'] == family
        assert rt.get_attr('RTA_NEWDST')[0]['label'] == label
        assert len(rt.get_attr('RTA_NEWDST')) == 1
        self.ip.route('del', **{'family': AF_MPLS,
                                'oif': self.ifaces[0],
                                'dst': {'label': 0x10,
                                        'bos': 1},
                                'via': {'family': family,
                                        'addr': address},
                                'newdst': {'label': label,
                                           'bos': 1}})
        assert len(self.ip.get_routes(oif=self.ifaces[0])) == 0

    def test_route_mpls_via_ipv4(self):
        self._test_route_mpls_via_ipv(socket.AF_INET,
                                      '172.16.0.1', 0x20)

    def test_route_mpls_via_ipv6(self):
        self._test_route_mpls_via_ipv(socket.AF_INET6,
                                      'fe80::5054:ff:fe4b:7c32', 0x20)

    @skip_if_not_supported
    def test_route_mpls_swap_newdst_simple(self):
        require_user('root')
        require_kernel(3)
        req = {'family': AF_MPLS,
               'oif': self.ifaces[0],
               'dst': {'label': 0x20,
                       'bos': 1},
               'newdst': {'label': 0x21,
                          'bos': 1}}
        self.ip.route('add', **req)
        rt = self.ip.get_routes(oif=self.ifaces[0])[0]
        assert rt.get_attr('RTA_DST')[0]['label'] == 0x20
        assert len(rt.get_attr('RTA_DST')) == 1
        assert rt.get_attr('RTA_NEWDST')[0]['label'] == 0x21
        assert len(rt.get_attr('RTA_NEWDST')) == 1
        self.ip.route('del', **req)
        assert len(self.ip.get_routes(oif=self.ifaces[0])) == 0

    @skip_if_not_supported
    def test_route_mpls_swap_newdst_list(self):
        require_user('root')
        require_kernel(3)
        req = {'family': AF_MPLS,
               'oif': self.ifaces[0],
               'dst': {'label': 0x20,
                       'bos': 1},
               'newdst': [{'label': 0x21,
                           'bos': 1}]}
        self.ip.route('add', **req)
        rt = self.ip.get_routes(oif=self.ifaces[0])[0]
        assert rt.get_attr('RTA_DST')[0]['label'] == 0x20
        assert len(rt.get_attr('RTA_DST')) == 1
        assert rt.get_attr('RTA_NEWDST')[0]['label'] == 0x21
        assert len(rt.get_attr('RTA_NEWDST')) == 1
        self.ip.route('del', **req)
        assert len(self.ip.get_routes(oif=self.ifaces[0])) == 0

    def test_route_multipath(self):
        require_user('root')
        self.ip.route('add',
                      dst='172.16.241.0',
                      mask=24,
                      multipath=[{'hops': 20,
                                  'ifindex': 1,
                                  'attrs': [['RTA_GATEWAY', '127.0.0.2']]},
                                 {'hops': 30,
                                  'ifindex': 1,
                                  'attrs': [['RTA_GATEWAY', '127.0.0.3']]}])
        assert grep('ip route show', pattern='172.16.241.0/24')
        assert grep('ip route show', pattern='nexthop.*127.0.0.2.*weight 21')
        assert grep('ip route show', pattern='nexthop.*127.0.0.3.*weight 31')
        self.ip.route('del', dst='172.16.241.0', mask=24)

    def test_route_multipath_helper(self):
        require_user('root')
        req = IPRouteRequest({'dst': '172.16.242.0/24',
                              'multipath': [{'hops': 20,
                                             'ifindex': 1,
                                             'gateway': '127.0.0.2'},
                                            {'hops': 30,
                                             'ifindex': 1,
                                             'gateway': '127.0.0.3'}]})
        self.ip.route('add', **req)
        assert grep('ip route show', pattern='172.16.242.0/24')
        assert grep('ip route show', pattern='nexthop.*127.0.0.2.*weight 21')
        assert grep('ip route show', pattern='nexthop.*127.0.0.3.*weight 31')
        self.ip.route('del', dst='172.16.242.0', mask=24)

    def test_route_change_existing(self):
        # route('replace', ...) should succeed, if route exists
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.50', mask=24)
        self.ip.route('add',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.1',
                      table=100)
        assert grep('ip route show table 100',
                    pattern='172.16.1.0/24.*172.16.0.1')
        self.ip.route('change',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.2',
                      table=100)
        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.1')
        assert grep('ip route show table 100',
                    pattern='172.16.1.0/24.*172.16.0.2')
        self.ip.flush_routes(table=100)
        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.2')

    def test_route_change_not_existing_fail(self):
        # route('change', ...) should fail, if no route exists
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.50', mask=24)
        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.1')
        try:
            self.ip.route('change',
                          dst='172.16.1.0',
                          mask=24,
                          gateway='172.16.0.1',
                          table=100)
        except NetlinkError as e:
            if e.code != errno.ENOENT:
                raise

    def test_route_replace_existing(self):
        # route('replace', ...) should succeed, if route exists
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.50', mask=24)
        self.ip.route('replace',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.1',
                      table=100)
        assert grep('ip route show table 100',
                    pattern='172.16.1.0/24.*172.16.0.1')
        self.ip.route('replace',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.2',
                      table=100)
        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.1')
        assert grep('ip route show table 100',
                    pattern='172.16.1.0/24.*172.16.0.2')
        self.ip.flush_routes(table=100)
        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.2')

    def test_route_replace_not_existing(self):
        # route('replace', ...) should succeed, if route doesn't exist
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.2', mask=24)
        self.ip.route('replace',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.1',
                      table=100)
        assert grep('ip route show table 100',
                    pattern='172.16.1.0/24.*172.16.0.1')
        self.ip.flush_routes(table=100)
        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.1')

    def test_flush_routes(self):
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.2', mask=24)
        self.ip.route('add',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.1',
                      table=100)
        self.ip.route('add',
                      dst='172.16.2.0',
                      mask=24,
                      gateway='172.16.0.1',
                      table=100)

        assert grep('ip route show table 100',
                    pattern='172.16.1.0/24.*172.16.0.1')
        assert grep('ip route show table 100',
                    pattern='172.16.2.0/24.*172.16.0.1')

        self.ip.flush_routes(table=100)

        assert not grep('ip route show table 100',
                        pattern='172.16.1.0/24.*172.16.0.1')
        assert not grep('ip route show table 100',
                        pattern='172.16.2.0/24.*172.16.0.1')

    def test_route_table_2048(self):
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], address='172.16.0.2', mask=24)
        self.ip.route('add',
                      dst='172.16.1.0',
                      mask=24,
                      gateway='172.16.0.1',
                      table=2048)
        assert grep('ip route show table 2048',
                    pattern='172.16.1.0/24.*172.16.0.1')
        remove_link('bala')

    def test_symbolic_flags_ifaddrmsg(self):
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], state='up')
        self.ip.addr('add', self.ifaces[0], '172.16.1.1', 24)
        addr = [x for x in self.ip.get_addr()
                if x.get_attr('IFA_LOCAL') == '172.16.1.1'][0]
        assert 'IFA_F_PERMANENT' in addr.flags2names(addr['flags'])

    def test_symbolic_flags_ifinfmsg(self):
        require_user('root')
        self.ip.link('set', index=self.ifaces[0], flags=['IFF_UP'])
        iface = self.ip.get_links(self.ifaces[0])[0]
        assert iface['flags'] & 1
        assert 'IFF_UP' in iface.flags2names(iface['flags'])
        self.ip.link('set', index=self.ifaces[0], flags=['!IFF_UP'])
        assert not (self.ip.get_links(self.ifaces[0])[0]['flags'] & 1)

    def test_updown_link(self):
        require_user('root')
        try:
            self.ip.link_up(*self.ifaces)
        except NetlinkError:
            pass
        assert self.ip.get_links(*self.ifaces)[0]['flags'] & 1
        try:
            self.ip.link_down(*self.ifaces)
        except NetlinkError:
            pass
        assert not (self.ip.get_links(*self.ifaces)[0]['flags'] & 1)

    def test_callbacks_positive(self):
        require_user('root')
        dev = self.ifaces[0]

        self.cb_counter = 0
        self.ip.register_callback(_callback,
                                  lambda x: x.get('index', None) == dev,
                                  (self, ))
        self.test_updown_link()
        assert self.cb_counter > 0
        self.ip.unregister_callback(_callback)

    def test_callbacks_negative(self):
        require_user('root')

        self.cb_counter = 0
        self.ip.register_callback(_callback,
                                  lambda x: x.get('index', None) == -1,
                                  (self, ))
        self.test_updown_link()
        assert self.cb_counter == 0
        self.ip.unregister_callback(_callback)

    def test_rename_link(self):
        require_user('root')
        dev = self.ifaces[0]
        try:
            self.ip.link_rename(dev, 'bala')
        except NetlinkError:
            pass
        assert len(self.ip.link_lookup(ifname='bala')) == 1
        try:
            self.ip.link_rename(dev, self.dev)
        except NetlinkError:
            pass
        assert len(self.ip.link_lookup(ifname=self.dev)) == 1

    def test_rules(self):
        assert len(get_ip_rules('-4')) == \
            len(self.ip.get_rules(socket.AF_INET))
        assert len(get_ip_rules('-6')) == \
            len(self.ip.get_rules(socket.AF_INET6))

    def test_addr(self):
        assert len(get_ip_addr()) == len(self.ip.get_addr())

    def test_links(self):
        assert len(get_ip_link()) == len(self.ip.get_links())

    def test_one_link(self):
        lo = self.ip.get_links(1)[0]
        assert lo.get_attr('IFLA_IFNAME') == 'lo'

    def test_default_routes(self):
        assert len(get_ip_default_routes()) == \
            len(self.ip.get_default_routes(family=socket.AF_INET, table=254))

    def test_routes(self):
        assert len(get_ip_route()) == \
            len(self.ip.get_routes(family=socket.AF_INET, table=255))
