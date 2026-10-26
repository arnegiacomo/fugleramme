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