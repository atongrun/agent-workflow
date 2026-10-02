package node

import (
	"errors"
	"fmt"
	"net/netip"
)

func parseAllowedSources(cfg Config) (map[netip.Addr]struct{}, error) {
	allowed := make(map[netip.Addr]struct{}, len(cfg.AllowedSourceIPs))
	for i, value := range cfg.AllowedSourceIPs {
		addr, err := netip.ParseAddr(value)
		if err != nil || addr.Zone() != "" || !(addr.IsGlobalUnicast() || addr.IsLoopback() || addr.IsLinkLocalUnicast()) {
			return nil, fmt.Errorf("node allowedSourceIPs[%d] must be an exact unicast IP address without a zone", i)
		}
		allowed[addr.Unmap()] = struct{}{}
	}
	// An empty address uses the command's loopback default. The handler still
	// checks peers, including when embedded in a different HTTP server.
	if cfg.ListenAddress != "" {
		listen, err := netip.ParseAddrPort(cfg.ListenAddress)
		if err != nil || listen.Addr().Zone() != "" {
			return nil, errors.New("node listenAddress must be a literal IP address and numeric port")
		}
		if !listen.Addr().Unmap().IsLoopback() && len(allowed) == 0 {
			return nil, errors.New("non-loopback node listenAddress requires explicit allowedSourceIPs")
		}
	}
	return allowed, nil
}

func (s *Server) sourceAllowed(remoteAddr string) bool {
	// Use the TCP peer only. Forwarding headers cannot grant access.
	peer, err := netip.ParseAddrPort(remoteAddr)
	if err != nil || peer.Addr().Zone() != "" {
		return false
	}
	addr := peer.Addr().Unmap()
	if len(s.allowedSources) == 0 {
		return addr.IsLoopback()
	}
	_, ok := s.allowedSources[addr]
	return ok
}
