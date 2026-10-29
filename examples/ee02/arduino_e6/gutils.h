#include <qrcode.h>

// Reverse a range of bytes: [first, last)
static void reverseBytes(uint8_t* first, uint8_t* last)
{
    while (first < last)
    {
        --last;

        if (first >= last)
            break;

        uint8_t temp = *first;
        *first = *last;
        *last = temp;

        ++first;
    }
}

// Rotate [first, middle) with [middle, last), preserving the
// byte order within both sections.
static void rotateBytes(
    uint8_t* first,
    uint8_t* middle,
    uint8_t* last)
{
    if (first == middle || middle == last)
        return;

    reverseBytes(first, middle);
    reverseBytes(middle, last);
    reverseBytes(first, last);
}

/*
 * Converts:
 *
 *   L0 L1 L2 ... Ln R0 R1 R2 ... Rn
 *
 * Into:
 *
 *   L0 R0 L1 R1 L2 R2 ... Ln Rn
 *
 * Each L/R block is one controller's portion of a row.
 */
static void interleaveControllerRows(
    uint8_t* buffer,
    size_t rowCount,
    size_t bytesPerHalfRow)
{
    if (rowCount <= 1)
        return;

    const size_t leftRowCount = rowCount / 2;
    const size_t rightRowCount = rowCount - leftRowCount;

    uint8_t* middle1 =
        buffer + leftRowCount * bytesPerHalfRow;

    uint8_t* middle2 =
        buffer + rowCount * bytesPerHalfRow;

    uint8_t* endOfMiddle =
        middle2 + leftRowCount * bytesPerHalfRow;

    /*
     * Before:
     *
     * [left first][left second][right first][right second]
     *
     * After:
     *
     * [left first][right first][left second][right second]
     */
    rotateBytes(middle1, middle2, endOfMiddle);

    // Interleave the first group.
    interleaveControllerRows(
        buffer,
        leftRowCount,
        bytesPerHalfRow);

    // Interleave the remaining group.
    interleaveControllerRows(
        buffer + (2 * leftRowCount * bytesPerHalfRow),
        rightRowCount,
        bytesPerHalfRow);
}

bool convertBuffer(
    uint8_t* buffer,
    size_t totalBytes,
    size_t imageWidth)
{
    static const uint8_t nibbleMap[16] = {
        0xF, // 0x0 -> 0xF
        0x0, // 0x1 -> 0x0
        0xB, // 0x2 -> 0xB
        0x6, // 0x3 -> 0x6
        0x0, // 0x4 -> 0x0
        0xD, // 0x5 -> 0xD
        0x2, // 0x6 -> 0x2
        0x0, // 0x7 -> 0x0
        0x0, // 0x8 -> 0x0
        0x0, // 0x9 -> 0x0
        0x0, // 0xA -> 0x0
        0x0, // 0xB -> 0x0
        0x0, // 0xC -> 0x0
        0x0, // 0xD -> 0x0
        0x0, // 0xE -> 0x0
        0x0  // 0xF -> 0x0
    };

    if (buffer == nullptr ||
        totalBytes == 0 ||
        imageWidth == 0)
    {
        return false;
    }

    /*
     * Four pixels are required to make one pair of equally
     * sized controller half-rows:
     *
     * 4 pixels / 2 pixels per byte = 2 bytes
     * 1 byte per controller
     */
    if ((imageWidth % 4) != 0)
        return false;

    const size_t bytesPerFullRow = imageWidth / 2;
    const size_t bytesPerHalfRow = imageWidth / 4;

    if (bytesPerFullRow == 0 ||
        (totalBytes % bytesPerFullRow) != 0)
    {
        return false;
    }

    const size_t rowCount = totalBytes / bytesPerFullRow;

    if (rowCount == 0)
        return false;

    // First assemble each complete row in place.
    interleaveControllerRows(
        buffer,
        rowCount,
        bytesPerHalfRow);

    // Then convert every nibble in the assembled buffer.
    for (size_t i = 0; i < totalBytes; ++i)
    {
        const uint8_t original = buffer[i];

        const uint8_t highNibble =
            nibbleMap[(original >> 4) & 0x0F];

        const uint8_t lowNibble =
            nibbleMap[original & 0x0F];

        buffer[i] =
            (uint8_t)((highNibble << 4) | lowNibble);
    }

    return true;
}

// Configuration states passed into the private rendering callback
static int _qr_scale = 1;
static uint8_t* _dest_buffer = nullptr;
static int _qr_width = 0;

/**
 * Sets a specific pixel in a standard monochrome 1-bit array (1 = Black, 0 = White)
 * Matches standard hardware formats where 8 horizontal pixels fit into 1 byte.
 */
inline void setBitmapPixel(uint8_t* buffer, int x, int y, int total_width, bool is_black) {
    if (!is_black) return; // Buffer is pre-cleared to 0 (White)
    
    int byte_index = (y * ((total_width + 7) / 8)) + (x / 8);
    int bit_index  = 7 - (x % 8); // MSB-first formatting
    
    buffer[byte_index] |= (1 << bit_index);
}

/**
 * Internal callback required by the Espressif library.
 * Performs the scaling and 90-degree clockwise transformation inline.
 */
void qr_bitmap_callback(esp_qrcode_handle_t qrcode) {
    int size = esp_qrcode_get_size(qrcode);
    int bytes_per_row = (_qr_width + 7) / 8;

    for (int y = 0; y < size; y++) {
        for (int x = 0; x < size; x++) {
            if (esp_qrcode_get_module(qrcode, x, y)) {
                // Scale up the QR modules into the target buffer pixels
                for (int py = 0; py < _qr_scale; py++) {
                    for (int px = 0; px < _qr_scale; px++) {
                        int target_x = (x * _qr_scale) + px;
                        int target_y = (y * _qr_scale) + py;

                        // Calculate typical 1-bit monochrome array packing indices
                        int byte_idx = (target_y * bytes_per_row) + (target_x / 8);
                        int bit_shift = 7 - (target_x % 8);

                        _dest_buffer[byte_idx] |= (1 << bit_shift); // 1 = Black module
                    }
                }
            }
        }
    }
}

/**
 * Generates an auto-sized QR code and processes it directly into a rotated 1-bit bitmap.
 * 
 * @param text          String payload to encode
 * @param pixel_scale   Size multiplier for individual modules
 * @param max_version   Cap for library layout calculation (2-40)
 * @param out_width     Returns the absolute pixel width/height of the resulting square bitmap
 * @param out_size      Returns the exact byte size allocated in memory
 * @return              Pointer to the allocated 1-bit buffer, or nullptr on failure. 
 *                      NOTE: You must call free() on this pointer when finished.
 */
uint8_t* generateQRBitmap(const char* text, int pixel_scale, int max_version, int &out_width, size_t &out_size) {
    // 1. We must temporarily get a sizing check. The library auto-optimizes versions up to max_version,
    // so we build a dummy frame configuration to let it pass the matrix size to our variables.
    _dest_buffer = nullptr;
    _qr_scale = pixel_scale;

    // Use a temporary configuration run to capture the footprint dimensions
    esp_qrcode_config_t pre_cfg = {
        .display_func = [](esp_qrcode_handle_t qrcode) {
            _qr_width = esp_qrcode_get_size(qrcode) * _qr_scale;
        },
        .max_qrcode_version = max_version,
        .qrcode_ecc_level = ESP_QRCODE_ECC_LOW
    };
    
    if (esp_qrcode_generate(&pre_cfg, text) != ESP_OK) {
        return nullptr;
    }

    // 2. Allocate the precise monochrome buffer required for the final width
    out_width = _qr_width;
    int bytes_per_row = (out_width + 7) / 8;
    out_size = bytes_per_row * out_width;
    
    uint8_t* bitmap = (uint8_t*)calloc(out_size, sizeof(uint8_t)); // Initialize completely to 0 (White)
    if (!bitmap) return nullptr;

    // 3. Point static references to our real buffer and execute the true processing pass
    _dest_buffer = bitmap;
    
    esp_qrcode_config_t active_cfg = {
        .display_func = qr_bitmap_callback, // Swapped from qr_bitmap_rotate_callback
        .max_qrcode_version = max_version,
        .qrcode_ecc_level = ESP_QRCODE_ECC_LOW
    };

    if (esp_qrcode_generate(&active_cfg, text) != ESP_OK) {
        free(bitmap);
        return nullptr;
    }

    return bitmap;
}
