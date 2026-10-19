package com.zbox.transfer.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.zbox.transfer.AppLanguage
import com.zbox.transfer.AppStrings
import com.zbox.transfer.Settings

/** 设置页：界面语言即时切换（读 Settings.language 的 Compose 状态，切完立即重组） */
@Composable
fun SettingsScreen() {
    val strings = AppStrings.current
    val selected = Settings.language
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Text(strings.settingsTitle, style = MaterialTheme.typography.titleLarge)
        Spacer(modifier = Modifier.height(16.dp))
        Text(strings.language, style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(8.dp))
        AppLanguage.entries.forEach { language ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { Settings.language = language }
                    .padding(vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(
                    selected = selected == language,
                    onClick = { Settings.language = language },
                )
                Text(language.displayName)
            }
        }
    }
}
