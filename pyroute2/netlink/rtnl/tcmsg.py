import struct

from pyroute2.netlink.generic import nlmsg
from pyroute2.netlink.generic import nla


class tcmsg(nlmsg):
    t_fields = (('family', 'B'),
                ('pad1', 'B'),
                ('pad2', 'H'),
                ('index', 'i'),
                ('handle', 'I'),
                ('parent', 'I'),
                ('info', 'I'))

    nla_map = (('TCA_UNSPEC', 'none'),
               ('TCA_KIND', 'asciiz'),
               ('TCA_OPTIONS', 'get_options'),
               ('TCA_STATS', 'stats'),
               ('TCA_XSTATS', 'hex'),
               ('TCA_RATE', 'hex'),
               ('TCA_FCNT', 'hex'),
               ('TCA_STATS2', 'stats2'),
               ('TCA_STAB', 'hex'))

    class stats(nla):
        t_fields = (('bytes', 'Q'),
                    ('packets', 'I'),
                    ('drop', 'I'),
                    ('overlimits', 'I'),
                    ('bps', 'I'),
                    ('pps', 'I'),
                    ('qlen', 'I'),
                    ('backlog', 'I'))

    class stats2(nla):
        nla_map = (('TCA_STATS_UNSPEC', 'none'),
                   ('TCA_STATS_BASIC', 'basic'),
                   ('TCA_STATS_RATE_EST', 'rate_est'),
                   ('TCA_STATS_QUEUE', 'queue'),
                   ('TCA_STATS_APP', 'hex'))

        class basic(nla):
            t_fields = (('bytes', 'Q'),
                        ('packets', 'Q'))

        class rate_est(nla):
            t_fields = (('bps', 'I'),
                        ('pps', 'I'))

        class queue(nla):
            t_fields = (('qlen', 'I'),
                        ('backlog', 'I'),
                        ('drops', 'I'),
                        ('requeues', 'I'),
                        ('overlimits', 'I'))

    def get_options(self, length, msg_type, buf):
        kind = self.get_attr('TCA_KIND')
        if kind:
            if kind[0] == 'pfifo_fast':
                return self.options_pfifo_fast
            elif kind[0] == 'tbf':
                return self.options_tbf
            elif kind[0] == 'sfq':
                if length >= struct.calcsize(self.options_sfq_v1.fmt):
                    return self.options_sfq_v1
                else:
                    return self.options_sfq_v0
            elif kind[0] == 'u32':
                return self.options_u32

        return self.hex

    class options_u32(nla):
        nla_map = (('TCA_U32_UNSPEC', 'none'),
                   ('TCA_U32_CLASSID', 'uint32'),
                   ('TCA_U32_HASH', 'uint32'),
                   ('TCA_U32_LINK', 'hex'),
                   ('TCA_U32_DIVISOR', 'uint32'),
                   ('TCA_U32_SEL', 'u32_sel'),
                   ('TCA_U32_POLICE', 'u32_police'),
                   ('TCA_U32_ACT', 'hex'),
                   ('TCA_U32_INDEV', 'hex'),
                   ('TCA_U32_PCNT', 'u32_pcnt'),
                   ('TCA_U32_MARK', 'u32_mark'))

        class u32_police(nla):
            nla_map = (('TCA_POLICE_UNSPEC', 'none'),
                       ('TCA_POLICE_TBF', 'police_tbf'),
                       ('TCA_POLICE_RATE', 'hex'),
                       ('TCA_POLICE_PEAKRATE', 'hex'),
                       ('TCA_POLICE_AVRATE', 'hex'),
                       ('TCA_POLICE_RESULT', 'hex'))

            class police_tbf(nla):
                t_fields = (('index', 'I'),
                            ('action', 'i'),
                            ('limit', 'I'),
                            ('burst', 'I'),
                            ('mtu', 'I'),
                            ('rate_cell_log', 'B'),
                            ('rate___reserved', 'B'),
                            ('rate_overhead', 'H'),
                            ('rate_cell_align', 'h'),
                            ('rate_mpu', 'H'),
                            ('rate', 'I'),
                            ('peak_cell_log', 'B'),
                            ('peak___reserved', 'B'),
                            ('peak_overhead', 'H'),
                            ('peak_cell_align', 'h'),
                            ('peak_mpu', 'H'),
                            ('peak', 'I'),
                            ('refcnt', 'i'),
                            ('bindcnt', 'i'),
                            ('capab', 'I'))

        class u32_sel(nla):
            t_fields = (('flags', 'B'),
                        ('offshift', 'B'),
                        ('nkeys', 'B'),
                        ('offmask', 'H'),  # FIXME: be16
                        ('off', 'H'),
                        ('offoff', 'h'),
                        ('hoff', 'h'),
                        ('hmask', 'I'),  # FIXME: be32
                        ('key_mask', 'I'),  # FIXME: be32
                        ('key_val', 'I'),  # FIXME: be32
                        ('key_off', 'i'),
                        ('key_offmask', 'i'))

        class u32_mark(nla):
            t_fields = (('val', 'I'),
                        ('mask', 'I'),
                        ('success', 'I'))

        class u32_pcnt(nla):
            t_fields = (('rcnt', 'Q'),
                        ('rhit', 'Q'),
                        ('kcnts', 'Q'))

    class options_pfifo_fast(nla):
        fmt = 'i' + 'B' * 16
        fields = tuple(['bands'] + ['mark_%02i' % (i) for i in
                                    range(1, 17)])

    class options_tbf(nla):
        nla_map = (('TCA_TBF_UNSPEC', 'none'),
                   ('TCA_TBF_PARMS', 'parms'),
                   ('TCA_TBF_RTAB', 'hex'),
                   ('TCA_TBF_PTAB', 'hex'))

        class parms(nla):
            t_fields = (('rate_cell_log', 'B'),
                        ('rate___reserved', 'B'),
                        ('rate_overhead', 'H'),
                        ('rate_cell_align', 'h'),
                        ('rate_mpu', 'H'),
                        ('rate', 'I'),
                        ('peak_cell_log', 'B'),
                        ('peak___reserved', 'B'),
                        ('peak_overhead', 'H'),
                        ('peak_cell_align', 'h'),
                        ('peak_mpu', 'H'),
                        ('peak', 'I'),
                        ('limit', 'I'),
                        ('buffer', 'I'),
                        ('mtu', 'I'))

    class options_sfq_v0(nla):
        t_fields = (('quantum', 'I'),
                    ('perturb_period', 'i'),
                    ('limit', 'I'),
                    ('divisor', 'I'),
                    ('flows', 'I'))

    class options_sfq_v1(nla):
        t_fields = (('quantum', 'I'),
                    ('perturb_period', 'i'),
                    ('limit_v0', 'I'),
                    ('divisor', 'I'),
                    ('flows', 'I'),
                    ('depth', 'I'),
                    ('headdrop', 'I'),
                    ('limit_v1', 'I'),
                    ('qth_min', 'I'),
                    ('qth_max', 'I'),
                    ('Wlog', 'B'),
                    ('Plog', 'B'),
                    ('Scell_log', 'B'),
                    ('flags', 'B'),
                    ('max_P', 'I'),
                    ('prob_drop', 'I'),
                    ('forced_drop', 'I'),
                    ('prob_mark', 'I'),
                    ('forced_mark', 'I'),
                    ('prob_mark_head', 'I'),
                    ('forced_mark_head', 'I'))