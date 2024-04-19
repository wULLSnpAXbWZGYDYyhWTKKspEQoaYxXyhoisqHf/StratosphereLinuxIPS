from slips_files.common.slips_utils import utils
from slips_files.core.evidence_structure.evidence import (
    Evidence,
    ProfileID,
    TimeWindow,
    Attacker,
    ThreatLevel,
    EvidenceType,
    IoCType,
    Direction,
    IDEACategory,
    Victim,
    Proto,
    Tag,
)


class VerticalPortscan:
    """
    Here's how the detection of vertical portscans is done
    1. Slips retrieves all destination IPs of the not
    established flows on TCP and UDP protocols
    2. For each dst IP, slips checks the amount of
    destination ports we connected to
    3. The first evidence will be triggered if the amount of
    destination ports for 1 IP is 5+
    4. then we combine evidence 3 by 3. for example
        evidence f 10,15,20 ports scanned will be combined into 1 evidence
        evidence of 15,30,35 ports scanned will be combined into 1 evidence
        etc.
    The result of this combining of evidence is that the dst ports
     scanned in each evidence will be = the
    previous scanned ports +15
    this combining is done to avoid duplicate evidence
    the downside to this is that if you do more than 1 portscan
    in the same timewindow, all portscans starting
    from the second portscan will be ignored if they don't exceed
    the number of dports of the first portscan
    so as a rule, each evidence should have X ports scanned. this
    X should ALWAYS be the last portscan+15,
    if this X is the last portscan +14, we don't
    set the evidence. we keep combining.
    3. Once the timewindow stops, Slips resets
     all counters, we go back to step 1
    """

    def __init__(self, db):
        self.db = db
        # to keep track of the max dports reported per timewindow
        self.cached_thresholds_per_tw = {}
        # The minimum amount of scanned ports to trigger an evidence
        # is increased exponentially every evidence, and is reset each timewindow
        self.port_scan_minimum_dports = 5

    def set_evidence_vertical_portscan(self, evidence: dict):
        """Sets the vertical portscan evidence in the db"""
        threat_level = ThreatLevel.HIGH
        saddr = evidence["profileid"].split("_")[-1]
        confidence = utils.calculate_confidence(evidence["pkts_sent"])
        description = (
            f'new vertical port scan to IP {evidence["dstip"]} from {saddr}. '
            f'Total {evidence["amount_of_dports"]} '
            f'dst {evidence["protocol"]} ports '
            f"were scanned. "
            f'Total packets sent to all ports: {evidence["pkts_sent"]}. '
            f"Confidence: {confidence}. by Slips"
        )

        attacker = Attacker(
            direction=Direction.SRC, attacker_type=IoCType.IP, value=saddr
        )
        victim = Victim(
            direction=Direction.DST,
            victim_type=IoCType.IP,
            value=evidence["dstip"],
        )
        twid = int(evidence["twid"].replace("timewindow", ""))
        evidence = Evidence(
            evidence_type=EvidenceType.VERTICAL_PORT_SCAN,
            attacker=attacker,
            threat_level=threat_level,
            confidence=confidence,
            description=description,
            profile=ProfileID(ip=saddr),
            timewindow=TimeWindow(number=twid),
            uid=evidence["uid"],
            timestamp=evidence["timestamp"],
            category=IDEACategory.RECON_SCANNING,
            conn_count=evidence["pkts_sent"],
            proto=Proto(evidence["protocol"].lower()),
            source_target_tag=Tag.RECON,
            victim=victim,
        )

        self.db.set_evidence(evidence)


    def is_dports_greater_or_eq_minimum_dports(self, dports: int) -> bool:
        return dports >= self.port_scan_minimum_dports


    @staticmethod
    def is_dports_greater_or_eq_last_evidence(
         dports: int, ports_reported_last_evidence: int
    ) -> bool:
        """
         To make sure the amount of dports reported
         each evidence is higher than the previous one +15
         so the first alert will always report 5
         dports, and then 20+,35+. etc
        :param dports: dports scanned in the current evidence
        :param ports_reported_last_evidence: the amount of
            ports reported in the last evidence in the current
            evidence's timewindow
        """
        return dports >= ports_reported_last_evidence + 15

    def should_set_evidence(self, dports: int, twid_threshold: int):
        """
        Makes sure the given dports are more than the minimum dports number
        we should alert on, and that is it more than the dports of
        the last evidence

        The goal is to never get an evidence that's
         1 or 2 ports more than the previous one so we dont
         have so many portscan evidence

        """
        return (
                self.is_dports_greater_or_eq_minimum_dports(dports)
                and
                self.is_dports_greater_or_eq_last_evidence(
                    dports,
                    twid_threshold
                )
        )


    def check_if_enough_dports_to_trigger_an_evidence(
        self, twid_identifier: str, amount_of_dports: int
    ) -> bool:
        """
        checks if the scanned sports are enough to trigger and evidence
        to make sure the amount of dports reported each evidence
        is higher than the previous one +15
        """
        twid_threshold: int = self.cached_thresholds_per_tw.get(twid_identifier)
        if self.should_set_evidence(amount_of_dports, twid_threshold):
            # keep track of the max reported dstips in the last evidence in this twid
            self.cached_thresholds_per_tw[twid_identifier] = amount_of_dports
            return True
        return False

    def get_not_established_dst_ips(
        self, protocol: str, state: str, profileid: str, twid: str
    ) -> dict:
        """
        Get the list of dstips that we tried to connect to (not established flows)
          these unknowns are the info this function retrieves
          profileid -> unknown_dstip:unknown_dstports

         here, the profileid given is the client.
         :return: the following dict
         {
             dst_ip: {
                 totalflows: total flows seen by the profileid
                 totalpkt: total packets seen by the profileid
                 totalbytes: total bytes sent by the profileid
                 stime: timestamp of the first flow seen from this profileid -> this dstip
                 uid: list of uids where the given profileid was
                        contacting the dst_ip on this dstport
                 dstports: dst ports seen in all flows where the given profileid was srcip
                     {
                         <str port>: < int spkts sent to this port>
                     }
             }
        """
        direction = "Dst"
        role = "Client"
        type_data = "IPs"

        dstips: dict = self.db.get_data_from_profile_tw(
            profileid, twid, direction, state, protocol, role, type_data
        )
        return dstips

    def get_cache_key(self, profileid: str, twid: str, dstip: str):
        """
        returns the key that identifies this vertical portscan in thhe
        given tw
        """
        return f"{profileid}:{twid}:dstip:{dstip}"

    def check(self, profileid, twid):
        """
        sets an evidence if a vertical portscan is detected
        """
        # if you're portscaning a port that is open it's gonna be established
        # the amount of open ports we find is gonna be so small
        # theoretically this is incorrect bc we'll be ignoring established connections,
        # but usually open ports are very few compared to the whole range
        # so, practically this is correct to avoid FP
        state = "Not Established"

        for protocol in ("TCP", "UDP"):
            dstips: dict = self.get_not_established_dst_ips(
                protocol, state, profileid, twid
            )

            # For each dstip, see if the amount of ports connections is over the threshold
            for dstip in dstips.keys():
                dst_ports: dict = dstips[dstip]["dstports"]
                # Get the total amount of pkts sent to all
                # ports on the same host
                pkts_sent = sum(dst_ports[dport] for dport in dst_ports)
                amount_of_dports = len(dst_ports)

                twid_identifier: str = self.get_cache_key(profileid, twid, dstip)
                if self.check_if_enough_dports_to_trigger_an_evidence(
                    twid_identifier, amount_of_dports
                ):
                    evidence_details = {
                        "timestamp": dstips[dstip]["stime"],
                        "pkts_sent": pkts_sent,
                        "protocol": protocol,
                        "profileid": profileid,
                        "twid": twid,
                        "uid": dstips[dstip]["uid"],
                        "amount_of_dports": amount_of_dports,
                        "dstip": dstip,
                        "state": state,
                    }

                    self.set_evidence_vertical_portscan(evidence_details)