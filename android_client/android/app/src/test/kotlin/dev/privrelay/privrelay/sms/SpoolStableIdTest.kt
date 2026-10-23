package dev.privrelay.privrelay.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.util.UUID

class SpoolStableIdTest {
    @Test fun liveAndImportedRowsUseTheSameDeterministicV7Identity() {
        val incoming = Spool.stableId("+15550100", "synthetic", 1_800_000_000_123, 4)
        val imported = Spool.stableId("+15550100", "synthetic", 1_800_000_000_123, 4)
        assertEquals(incoming, imported)
        assertEquals(7, UUID.fromString(incoming).version())
        assertNotEquals(incoming, Spool.stableId("+15550100", "synthetic", 1_800_000_000_123, 5))
    }
}
