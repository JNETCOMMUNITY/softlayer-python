"""
    SoftLayer.network
    ~~~~~~~~~~~~~~~~~
    Network Manager/helpers

    :copyright: (c) 2013, SoftLayer Technologies, Inc. All rights reserved.
    :license: BSD, see LICENSE for more details.
"""

from SoftLayer.utils import NestedDict, query_filter, IdentifierMixin, \
    resolve_ids


class NetworkManager(IdentifierMixin, object):
    """ Manage Networks """
    def __init__(self, client):
        #: A valid `SoftLayer.API.Client` object that will be used for all
        #: actions.
        self.client = client
        #: Reference to the SoftLayer_Account API object.
        self.account = client['Account']
        #: Reference to the SoftLayer_Network_Vlan object.
        self.vlan = client['Network_Vlan']
        self.subnet = client['Network_Subnet']
        self.subnet_resolvers = [self._get_subnet_by_identifier]

    def add_subnet(self, type, quantity=None, vlan_id=None, version=4,
                   test_order=False):
        package = self.client['Product_Package']
        category = 'sov_sec_ip_addresses_priv'
        if version == 4:
            if type == 'global':
                quantity = 0
                category = 'global_ipv4'
            elif type == 'public':
                category = 'sov_sec_ip_addresses_pub'
        else:
            category = 'static_ipv6_addresses'
            if type == 'global':
                quantity = 0
                category = 'global_ipv6'
                desc = 'Global'
            elif type == 'public':
                desc = 'Portable'

        price_id = None
        quantity = str(quantity)
        for item in package.getItems(id=0, mask='mask[itemCategory]'):
            category_code = item.get('itemCategory', {}).get('categoryCode')
            if category_code == category and item['capacity'] == quantity:
                if version == 4 or (version == 6
                                    and desc in item['description']):
                    price_id = item['prices'][0]['id']

        order = {
            'packageId': 0,
            'prices': [{'id': price_id}],
            'quantity': 1,
        }

        if type != 'global':
            order['endPointVlanId'] = vlan_id

        if not price_id:
            return None

        func = 'placeOrder'
        if test_order:
            func = 'verifyOrder'
        func = getattr(self.client['Product_Order'], func)

        # This is necessary in order for the XML-RPC endpoint to select the
        # correct order container. Without this, placing the order will fail.
        order['complexType'] = \
            'SoftLayer_Container_Product_Order_Network_Subnet'
        return func(order)

    def cancel_subnet(self, id):
        """ Cancels the specified subnet.

        :param int id: The ID of the subnet to be cancelled.
        """
        subnet = self.get_subnet(id=id, mask='mask[id, billingItem.id]')
        billing_id = subnet['billingItem']['id']

        billing_item = self.client['Billing_Item']
        return billing_item.cancelService(id=billing_id)

    def ip_lookup(self, ip):
        """ Looks up an IP address and returns network information about it.

        :param string ip: An IP address. Can be IPv4 or IPv6
        :returns: A dictionary of information about the IP

        """
        mask = [
            'hardware',
            'virtualGuest'
        ]
        mask = 'mask[%s]' % ','.join(mask)
        obj = self.client['Network_Subnet_IpAddress']
        return obj.getByIpAddress(ip, mask=mask)

    def get_vlan(self, id):
        """ Returns information about a single VLAN.

        :param int id: The unique identifier for the VLAN
        :returns: A dictionary containing a large amount of information about
                  the specified VLAN.

        """
        return self.vlan.getObject(id=id, mask=self._get_vlan_mask())

    def get_subnet(self, id, **kwargs):
        """ Returns information about a single subnet.

        :param string id: Either the ID for the subnet or its network
                          identifier
        :returns: A dictionary of information about the subnet
        """
        if 'mask' not in kwargs:
            kwargs['mask'] = 'mask[%s]' % ','.join(self._get_subnet_mask())

        id = resolve_ids(id, self.subnet_resolvers)[0]
        return self.subnet.getObject(id=id, **kwargs)

    def list_vlans(self, datacenter=None, vlan_number=None, **kwargs):
        """ Display a list of all VLANs on the account.

        This provides a quick overview of all VLANs including information about
        data center residence and the number of devices attached.

        :param string datacenter: If specified, the list will only contain
                                  VLANs in the specified data center.
        :param int vlan_number: If specified, the list will only contain the
                                VLAN matching this VLAN number.
        :param dict \*\*kwargs: response-level arguments (limit, offset, etc.)

        """
        _filter = NestedDict(kwargs.get('filter') or {})

        if vlan_number:
            _filter['networkVlans']['vlanNumber'] = query_filter(vlan_number)

        if datacenter:
            _filter['networkVlans']['primaryRouter']['datacenter']['name'] = \
                query_filter(datacenter)

        kwargs['filter'] = _filter.to_dict()

        return self._get_vlans(**kwargs)

    def list_subnets(self, identifier=None, datacenter=None, version=0,
                     **kwargs):
        """ Display a list of all subnets on the account.

        This provides a quick overview of all subnets including information
        about data center residence and the number of devices attached.

        :param string datacenter: If specified, the list will only contain
                                  subnets in the specified data center.
        :param dict \*\*kwargs: response-level arguments (limit, offset, etc.)

        """
        if 'mask' not in kwargs:
            mask = self._get_subnet_mask()
            kwargs['mask'] = 'mask[%s]' % ','.join(mask)

        _filter = NestedDict(kwargs.get('filter') or {})

        if identifier:
            _filter['subnets']['networkIdentifier'] = query_filter(identifier)
        if datacenter:
            _filter['subnets']['datacenter']['name'] = \
                query_filter(datacenter)
        if version:
            _filter['subnets']['version'] = query_filter(version)

        kwargs['filter'] = _filter.to_dict()

        results = self.account.getSubnets(**kwargs)
        return results

    def summary_by_datacenter(self):
        """ Provides a dictionary with a summary of all network information on
        the account, grouped by data center.

        The resultant dictionary is primarily useful for statistical purposes.
        It contains count information rather than raw data. If you want raw
        information, see the :func:`list_vlans` method instead.

        :returns: A dictionary keyed by data center with the data containing a
                  series of counts for hardware, subnets, CCIs, and other
                  objects residing within that data center.

        """
        datacenters = {}
        for vlan in self._get_vlans():
            dc = vlan['primaryRouter']['datacenter']
            name = dc['name']
            if name not in datacenters:
                datacenters[name] = {
                    'hardwareCount': 0,
                    'networkingCount': 0,
                    'primaryIpCount': 0,
                    'subnetCount': 0,
                    'virtualGuestCount': 0,
                    'vlanCount': 0,
                }

            datacenters[name]['vlanCount'] += 1
            datacenters[name]['hardwareCount'] += len(vlan['hardware'])
            datacenters[name]['networkingCount'] += \
                len(vlan['networkComponents'])
            datacenters[name]['primaryIpCount'] += \
                vlan['totalPrimaryIpAddressCount']
            datacenters[name]['subnetCount'] += len(vlan['subnets'])
            datacenters[name]['virtualGuestCount'] += \
                len(vlan['virtualGuests'])

        return datacenters

    def _get_subnet_by_identifier(self, identifier):
        """ Returns the ID of the subnet matching the specified identifier.

        :param string identifier: The identifier to look up
        :returns: The ID of the matching subnet or None
        """
        results = self.list_subnets(identifier=identifier, mask='id')
        return [result['id'] for result in results]

    def _get_vlans(self, **kwargs):
        """ Returns a list of VLANs.

        Wrapper method for preventing duplicated code.

        :param dict \*\*kwargs: response-level arguments (limit, offset, etc.)

        """
        return self.account.getNetworkVlans(mask=self._get_vlan_mask(),
                                            **kwargs)

    @staticmethod
    def _get_subnet_mask():
        """ Returns the standard subnet object mask.

        Wrapper method to prevent duplicated code.

        """
        return [
            'hardware',
            'datacenter',
            'ipAddressCount',
            'virtualGuests',
        ]

    @staticmethod
    def _get_vlan_mask():
        """ Returns the standard VLAN object mask.

        Wrapper method for preventing duplicated code.

        """
        mask = [
            'firewallInterfaces',
            'hardware',
            'networkComponents',
            'primaryRouter[id, fullyQualifiedDomainName, datacenter]',
            'subnets',
            'totalPrimaryIpAddressCount',
            'virtualGuests',
        ]

        return 'mask[%s]' % ','.join(mask)
