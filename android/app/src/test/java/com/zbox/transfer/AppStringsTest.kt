package com.zbox.transfer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AppStringsTest {
    @Test fun normalizesSupportedLocales() {
        assertEquals(AppLanguage.ZH, AppLanguage.fromLocaleTag("zh_CN"))
        assertEquals(AppLanguage.EN, AppLanguage.fromLocaleTag("en-GB"))
        assertEquals(AppLanguage.EN, AppLanguage.fromLocaleTag("ja-JP"))
        assertNull(AppLanguage.fromLocaleTag(""))
    }

    @Test fun unresolvedLocaleFallsBackToChinese() {
        assertEquals(AppLanguage.ZH, AppLanguage.detect(""))
    }
}
