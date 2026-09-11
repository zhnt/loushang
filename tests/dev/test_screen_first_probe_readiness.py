def test_embedded_probe_does_not_treat_loading_welcome_as_session_ready():
    from tests.coding._g18_native_probe import ready

    class Driver:
        def read_until(self, predicate, *, timeout):
            assert timeout == 35
            first_frame = "Welcome to Loushang CLI\x1b[?2004h\x1b[?1004hLoading session"
            assert not predicate(first_frame)
            assert predicate(first_frame + "\nmodel | cwd | perm=standard")

    ready(Driver(), embedded=True)
