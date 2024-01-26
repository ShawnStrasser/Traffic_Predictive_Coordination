# Description: Gets volume and occupancy data from detectors using SNMP
# A DuckDB connection object is passed in as an argument, along with a list of signals.
# Volume and occupancy data is retrieved from each signal and saved to the database.
# Timestamps are automatically generated by the database using the DEFAULT keyword.

from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity

class GetVolumeOccupancy:
    '''
    Takes in list of tuples: (signal name, IP, detectors),
    uses SNMP to get volume and occupancy for each detector,
    and saves data to database.
    '''
    def __init__(self):

        # OID's from NTCIP 1202 v03
        self.oid_volume = '1.3.6.1.4.1.1206.4.2.1.2.5.4.1.1' # volume base table
        self.oid_occupancy = '1.3.6.1.4.1.1206.4.2.1.2.5.4.1.2' # occupancy base table

    def get_snmp_data(self, con, _ip_address, _oid_base, _identifiers, _port=161, _community='public'): 
        values = []

        for identifier in _identifiers:
            # Construct the full OID for each identifier
            object_identity = ObjectIdentity(_oid_base + '.' + str(identifier))

            # SNMP GET request
            error_indication, error_status, error_index, var_binds = next(
                getCmd(SnmpEngine(),
                    CommunityData(_community, mpModel=0),  # SNMPv1
                    UdpTransportTarget((_ip_address, _port)),
                    ContextData(),
                    ObjectType(object_identity))
            )

            if error_indication:
                print(error_indication)
                # Record error to Logs (timestamp DATETIME, event VARCHAR, message VARCHAR)
                con.execute(f"INSERT INTO Logs VALUES (DEFAULT, 'error', '{error_indication}')")
            elif error_status:
                print(f'{error_status.prettyPrint()} at {error_index}')
                # Record error to Logs (timestamp DATETIME, event VARCHAR, message VARCHAR)
                con.execute(f"INSERT INTO Logs VALUES (DEFAULT, 'error', '{error_status} at {error_index}')")
            else:
                for var_bind in var_binds:
                     # Save values to a list
                    values.append(int(var_bind[1]))
        ### NEED TO MAKE UPDATE TO ACCOUNT FOR ERRORS BETTER ###
        return values
                    

    def get_data(self, con, signals, port=161, community='public'):
        # Iterate through signals
        for signal in signals:
            # Unpack signal
            name, ip_address, detectors = signal
            # Convert detectors to list
            detectors = detectors.split(',')

            # Get volume and occupancy
            volumes = self.get_snmp_data(con, ip_address, self.oid_volume, detectors, port, community)
            occupancies = self.get_snmp_data(con, ip_address, self.oid_occupancy, detectors, port, community)
            
            for idx, detector in enumerate(detectors):
                # Save data to database
                con.execute(f"INSERT INTO Volumes VALUES ('{name}', {detector}, DEFAULT, {volumes[idx]})")
                con.execute(f"INSERT INTO Occupancies VALUES ('{name}', '{detector}', DEFAULT, {occupancies[idx]/200})")