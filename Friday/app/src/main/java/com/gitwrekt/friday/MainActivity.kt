package com.gitwrekt.friday

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { FridayScreen() }
        }
    }
}

private val Background = Color(0xFF0E1116)
private val Surface = Color(0xFF1F2630)

@Composable
fun FridayScreen(vm: AssistantViewModel = viewModel()) {
    val context = LocalContext.current
    var hasMic by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val micLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasMic = granted
        if (granted) vm.onMicTapped()
    }

    val accent = Color(0xFFFF8A80)
    val listState = rememberLazyListState()
    LaunchedEffect(vm.messages.size) {
        if (vm.messages.isNotEmpty()) listState.animateScrollToItem(vm.messages.lastIndex)
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(Background)
            .safeDrawingPadding()
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(Persona.displayName, color = accent, fontSize = 22.sp)
            if (vm.offline) {
                Text("  offline mode", color = Color.Gray, fontSize = 14.sp)
            }
            Spacer(Modifier.weight(1f))
            TextButton(onClick = vm::clearHistory) { Text("Clear") }
        }

        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 12.dp),
        ) {
            items(vm.messages) { m -> Bubble(m, accent) }
        }

        if (vm.partial.isNotBlank()) {
            Text(
                "\u201C${vm.partial}\u201D",
                color = Color.LightGray,
                fontStyle = FontStyle.Italic,
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }
        vm.error?.let {
            Text(it, color = Color(0xFFFF6E6E), modifier = Modifier.padding(bottom = 8.dp))
        }

        val name = Persona.displayName
        val label = when (vm.status) {
            Status.IDLE -> "Talk to $name"
            Status.LISTENING -> "Listening\u2026  (tap to cancel)"
            Status.THINKING -> "Thinking\u2026  (tap to cancel)"
            Status.SPEAKING -> "Speaking\u2026  (tap to interrupt)"
        }
        Button(
            onClick = {
                if (hasMic) vm.onMicTapped() else micLauncher.launch(Manifest.permission.RECORD_AUDIO)
            },
            colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = Color.Black),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth().height(72.dp),
        ) { Text(label, fontSize = 18.sp) }

        TextButton(onClick = vm::cycleVoice, modifier = Modifier.fillMaxWidth()) {
            Text(
                "Voice: ${vm.voiceLabel}  \u25B8",
                color = Color.Gray,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun Bubble(m: ChatMessage, accent: Color) {
    val mine = m.role == "user"
    Box(
        Modifier.fillMaxWidth(),
        contentAlignment = if (mine) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Text(
            m.text,
            color = if (mine) Color.Black else Color.White,
            modifier = Modifier
                .widthIn(max = 300.dp)
                .background(if (mine) accent else Surface, RoundedCornerShape(14.dp))
                .padding(12.dp),
        )
    }
}
