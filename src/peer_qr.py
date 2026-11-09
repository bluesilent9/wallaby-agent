"""Local QR-image reader. Decoded text still requires signed invitation checks."""
import base64,io,warnings
MAX_BYTES=1536*1024
MAX_PIXELS=12_000_000

def decode(encoded):
    if not isinstance(encoded,str) or len(encoded)>MAX_BYTES*4//3+4:raise ValueError('Choose a PNG or JPEG QR image smaller than 1.5 MiB.')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):raise ValueError('Invalid QR image.')
    if not raw or len(raw)>MAX_BYTES:raise ValueError('QR image is too large.')
    from PIL import Image
    import zxingcpp
    from denial_storage import strict_json
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw),formats=['PNG','JPEG']) as image:
                if image.width*image.height>MAX_PIXELS or image.width>8192 or image.height>8192:raise ValueError('QR image dimensions are too large.')
                image.load();image=image.convert('L')
                results=zxingcpp.read_barcodes(image,formats=zxingcpp.BarcodeFormat.QRCode)
        if len(results)!=1 or not results[0].valid or len(results[0].text)>16384:raise ValueError('Choose an image containing exactly one clear pairing QR.')
        envelope=strict_json(results[0].text.encode())
        if not isinstance(envelope,dict) or not isinstance(envelope.get('message'),dict) or envelope['message'].get('kind')!='agent_invitation':raise ValueError('This is not a device pairing QR.')
        return {'envelope':envelope,'message':'QR read locally. Confirm its independent source, then connect to validate its signature and expiry.'}
    except (OSError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise ValueError('The QR image is invalid or too large.')
