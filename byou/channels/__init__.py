"""Byou channel adapters — pluggable communication channels (voice/email/im/...).

Each channel implements ChannelPort from byou.channels.contracts.
Core never imports channel-specific internals; it only sees the port.
"""
