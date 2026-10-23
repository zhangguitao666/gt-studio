"""Source data-level interpretation; Auto QTRLE follows captured Resolve cases."""
MODES = ('Auto', 'Full', 'Video')


def level_filters(media):
    """Return pre-resize decoder overrides and post-resize RGB float mapping."""
    mode = media.get('data_level', 'Auto')
    if mode not in MODES:
        raise ValueError('Data level must be Auto, Full or Video')
    if mode == 'Auto':
        mode = 'Video' if media.get('video_codec') == 'qtrle' else 'Auto'
    pixel_format = media.get('pixel_format', '')
    rgb = pixel_format.startswith(('rgb', 'bgr', 'gbr', 'argb', 'abgr'))
    if rgb and mode == 'Video':
        # Video black/white at 16/235 for the captured 8-bit RGB source.
        # Keep negative and superwhite values until the graph is evaluated.
        return '', ',' + 'geq=' + ':'.join(f"{c}='({c}(X,Y)*255-16)/219'" for c in ('r','g','b')) + ":a='alpha(X,Y)'"
    if not rgb and mode != 'Auto':
        return f',scale=in_range={"full" if mode == "Full" else "tv"}:out_range=full,format=gbrapf32le', ''
    return '', ''
